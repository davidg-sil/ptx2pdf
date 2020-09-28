
import configparser, os, re, regex, random, collections
from .texmodel import ModelMap, TexModel, universalopen
from .ptsettings import ParatextSettings, allbooks, books, bookcodes, chaps
from .font import TTFont, cachepath, cacheremovepath
from ptxprint.utils import _
import pathlib, os, sys
from configparser import NoSectionError, NoOptionError, _UNSET
from zipfile import ZipFile, ZIP_DEFLATED
from io import StringIO
import datetime, time
from shutil import copyfile, copytree, move

VersionStr = "1.1.9"

pdfre = re.compile(r".+[\\/](.+)\.pdf")

varpaths = (
    ('prjdir', ('settings_dir', 'prjid')),
    ('settingsdir', ('settings_dir',)),
    ('workingdir', ('working_dir',)),
)

def newBase(fpath):
    doti = fpath.rfind(".")
    f = os.path.basename(fpath[:doti])
    cl = re.findall(r"(?i)_?((?=ab|cn|co|hk|lb|bk|ba|dy|gt|dh|mh|mn|wa|dn|ib)..\d{5})[abc]?$", f)
    if cl:
        return cl[0].lower()
    else:
        return re.sub('[()&+,.;: \-]', '_', f.lower())

def refKey(r, info=""):
    m = re.match(r"^(\D*)\s*(\d*)\.?(\d*)(\S*?)$", r)
    if m:
        return (books.get(m.group(1)[:3], "100"), int(m.group(2) or 0), int(m.group(3) or 0), m.group(1)[3:], info, m.group(4))
    else:
        return (r, "", 0, 0, info)

class Path(pathlib.Path):

    _flavour = pathlib._windows_flavour if os.name == "nt" else pathlib._posix_flavour

    @staticmethod
    def create_varlib(aView):
        res = {}
        for k, v in varpaths:
            res[k] = pathlib.Path(*[getattr(aView, x) for x in v])
        res['pdfassets'] = pathlib.Path(os.path.abspath(os.path.dirname(__file__)), 'PDFassets')
        return res

    def __new__(cls, txt, view=None):
        if view is None or not txt.startswith("${"):
            return pathlib.Path.__new__(cls, txt)
        varlib = cls.create_varlib(view)
        k = txt[2:txt.find("}")]
        return pathlib.Path.__new__(cls, varlib[k], txt[len(k)+4:])

    def withvars(self, aView):
        varlib = self.create_varlib(aView)
        bestl = len(str(self))
        bestk = None
        for k, v in varlib.items():
            try:
                rpath = self.relative_to(v)
            except ValueError:
                continue
            if len(str(rpath)) < bestl:
                bestk = k
        if bestk is not None:
            return "${"+bestk+"}/"+rpath.as_posix()
        else:
            return self.as_posix()

posparms = ["alt", "src", "size", "pgpos", "copy", "caption", "ref", "x-xetex", "mirror", "scale"]
pos3parms = ["src", "size", "pgpos", "ref", "copy", "alt", "x-xetex", "mirror", "scale"]

class ViewModel:
    _attributes = {
        # modelname: (attribute, isMultiple, label)
        "project/frontincludes":    ("FrontPDFs", True, "lb_inclFrontMatter"),
        "project/backincludes":     ("BackPDFs", True, "lb_inclBackMatter"),
        "project/selectscript":     ("customScript", False, None),
        "paper/watermarkpdf":       ("watermarks", False, "lb_applyWatermark"),
        "fancy/pageborderpdf":      ("pageborder", False, "lb_inclPageBorder"),
        "fancy/sectionheaderpdf":   ("sectionheader", False, "lb_inclSectionHeader"),
        "fancy/endofbookpdf":       ("endofbook", False, "lb_inclEndOfBook"),
        "fancy/versedecoratorpdf":  ("versedecorator", False, "lb_inclVerseDecorator"),
        "document/customfigfolder": ("customFigFolder", False, None),
        "document/customoutputfolder": ("customOutputFolder", False, None)
    }
    _settingmappings = {
        "notes/xrcallers": "crossrefs",
        "notes/fncallers": "footnotes"
    }
    _activekeys = {
        "document/diglotsecprj": "updateDiglotConfigList"
    }

    def __init__(self, settings_dir, workingdir, userconfig, scriptsdir):
        self.settings_dir = settings_dir
        self.fixed_wd = workingdir != None
        self.working_dir = workingdir
        self.userconfig = userconfig
        self.scriptsdir = scriptsdir
        self.ptsettings = None
        self.customScript = None
        self.FrontPDFs = None
        self.BackPDFs = None
        self.watermarks = None
        self.pageborder = None
        self.sectionheader = None
        self.endofbook = None
        self.versedecorator = None
        self.customFigFolder = None
        self.customOutputFolder = None
        self.prjid = None
        self.configId = None
        self.isDisplay = False
        self.tempFiles = []

        # private to this implementation
        self.dict = {}
        self.setDate()

    def setDate(self):
        t = datetime.datetime.now()
        zd = datetime.timedelta(seconds=-(time.altzone if time.daylight else time.timezone))
        tzhrs = zd.days * 24 + (zd.seconds // 3600)
        tzmins = (zd.seconds % 3600) // 60
        
        if tzhrs == 0:
            tzstr = "Z"
        else:
            tzstr = "{0:+03}'{1:02}'".format(tzhrs, tzmins)
        self.set("_pdfdate", t.strftime("%Y%m%d%H%M%S")+tzstr)
        self.set("_date", t.strftime("%Y-%m-%d %H:%M:%S ")+tzstr)

    def doError(self, txt, secondary=None, title=None):
        print(txt)
        if secondary is not None:
            print(secondary)

    def msgQuestion(self, q1, q2):
        print("Answering \"no\" to: " + q1)
        print(q2)
        return False

    def parse_fontname(self, font):
        m = re.match(r"^(.*?)(\d+(?:\.\d+?)?)$", font)
        if m:
            return [m.group(1), int(m.group(2))]
        else:
            return [font, 0]

    def get(self, wid, default=None, sub=0, asstr=False, skipmissing=False):
        if wid.startswith("bl_"):
            return (self.dict.get(wid + "/name", None), self.dict.get(wid + "/style", None))
        return self.dict.get(wid, default)

    def set(self, wid, value, skipmissing=False):
        if wid.startswith("bl_"):
            self.setFont(wid, *value)
        elif wid.startswith("s_"):
            self.dict[wid] = "{:.3f}".format(float(value))
        else:
            self.dict[wid] = value

    def baseTeXPDFname(self):
        bks = self.getBooks()
        if self.working_dir == None:
            self.working_dir = os.path.join(self.settings_dir, self.prjid, 'PrintDraft')
        cfgname = self.configName()
        if cfgname is None:
            cfgname = ""
        else:
            cfgname = "-" + cfgname
        if len(bks) > 1:
            fname = "ptxprint{}-{}_{}{}".format(cfgname, bks[0], bks[-1], self.prjid)
        else:
            fname = "ptxprint{}-{}{}".format(cfgname, bks[0], self.prjid)
        if not os.path.exists(self.working_dir):
            os.makedirs(self.working_dir)
        return os.path.join(self.working_dir, fname)
        
    def getBooks(self, scope=None):
        bl = self.get("t_booklist", "").split()
        if scope is None:
            scope = self.get("r_book")
        if scope == "single":
            return [self.get("ecb_book")]
        elif scope == "multiple" and len(bl):
            blst = []
            for b in bl:
                bname = self.getBookFilename(b, self.prjid)
                if os.path.exists(os.path.join(self.settings_dir, self.prjid, bname)):
                    blst.append(b)
            return blst
        elif scope == "module":
            return [self.get("ecb_biblemodule")]
        else:
            # return self.booklist
            return []

    def _getPtSettings(self, prjid):
        if self.ptsettings is None:
            self.ptsettings = ParatextSettings(self.settings_dir, self.prjid)
        if prjid is None:
            prjid = self.prjid
        if prjid != self.prjid:
            ptsettings = ParatextSettings(self.settings_dir, prjid)
        else:
            ptsettings = self.ptsettings
        return ptsettings

    def getBookFilename(self, bk, prjid=None):
        ptsettings = self._getPtSettings(prjid)
        fbkfm = ptsettings['FileNameBookNameForm']
        bknamefmt = (ptsettings['FileNamePrePart'] or "") + \
                    fbkfm.replace("MAT","{bkid}").replace("41","{bkcode}") + \
                    (ptsettings['FileNamePostPart'] or "")
        fname = bknamefmt.format(bkid=bk, bkcode=bookcodes.get(bk, 0))
        return fname

    def setFont(self, btn, name, style):
        self.dict[btn+"/name"] = name
        self.dict[btn+"/style"] = style

    def onFontChanged(self, fbtn):
        font_info = self.get("bl_fontR")
        f = TTFont(*font_info)
        if "Silf" in f:
            self.set("c_useGraphite", True)
        else:
            self.set("c_useGraphite", False)
        silns = "{urn://www.sil.org/ldml/0.1}"
        if self.get("t_fontfeatures") == "":
            d = self.ptsettings.find_ldml('.//special/{1}external-resources/{1}font[@name="{0}"]'.format(f.family, silns))
            if d is not None:
                featstring = d.get('features', '')
                self.set("t_fontfeatures", featstring)
        for s in ('Bold', 'Italic', 'Bold Italic'):
            sid = "".join(x[0] for x in s.split())
            esid = s.lower().replace(" ", "")
            w = "bl_font"+sid
            nf = TTFont(f.family, style = " ".join(s.split()))
            if nf.filename is None:
                styles = s.split()
                if len(styles) > 1:
                    bf = TTFont(f.family, style=styles[0])
                    if bf.filename is not None:
                        self.set("s_{}embolden".format(esid), 0)
                        styles.pop(0)
                    else:
                        bf = f
                else:
                    bf = f
                self.set(w, (bf.family, bf.style))
                self.set("c_fake"+esid, True)
                for t in styles:
                    if t == 'Bold':
                        self.set("s_{}embolden".format(esid), 2)
                    elif t == 'Italic':
                        self.set("s_{}slant".format(esid), 0.15)
            else:
                self.set(w, (nf.family, nf.style))
                self.set("c_fake"+esid, False)

    def updateSavedConfigList(self):
        pass

    def updateDiglotConfigList(self):
        pass

    def updateBookList(self):
        pass

    def setPrjid(self, prjid, saveCurrConfig=False):
        return self.updateProjectSettings(prjid, configName="Default", saveCurrConfig=saveCurrConfig)

    def setConfigId(self, configid, saveCurrConfig=False, force=False):
        return self.updateProjectSettings(self.prjid, saveCurrConfig=saveCurrConfig, configName=configid, forceConfig=force)

    def _copyConfig(self, oldcfg, newcfg, moving=False):
        oldp = self.configPath(cfgname=oldcfg)
        newp = self.configPath(cfgname=newcfg)
        if not os.path.exists(newp):
            os.makedirs(newp)
            for f in ('ptxprint-mods.sty', 'ptxprint-mods.tex', 'ptxprint.cfg', 'PicLists', 'AdjLists'):
                srcp = os.path.join(oldp, f)
                destp = os.path.join(newp, f)
                if os.path.exists(srcp):
                    if moving:
                        move(srcp, destp)
                    elif os.path.isdir(srcp):
                        os.makedirs(destp, exist_ok=True)
                        for p in os.listdir(srcp):
                            op = re.sub(r"-[^-]+\.", "-"+newcfg+".", p)
                            copyfile(os.path.join(srcp, p), os.path.join(destp, op))
                    else:
                        copyfile(srcp, destp)

    def updateProjectSettings(self, prjid, saveCurrConfig=False, configName=None, forceConfig=False):
        currprj = self.prjid
        currcfg = self.configId
        readConfig = False
        if currprj is None or currprj != prjid:
            if currprj is not None and saveCurrConfig:
                self.writeConfig()
                self.updateSavedConfigList()
                self.set("t_savedConfig", "")
                self.set("t_configNotes", "")
                fdir = os.path.join(self.settings_dir, currprj, "shared", "fonts")
                if os.path.exists(fdir):
                    cacheremovepath(fdir)
            self.ptsettings = None
            self.prjid = self.get("fcb_project") if prjid is None else prjid
            self.configId = None
            if self.prjid:
                self.ptsettings = ParatextSettings(self.settings_dir, self.prjid)
                self.updateBookList()
            if not self.prjid:
                return False
            if not self.fixed_wd:
                self.working_dir = os.path.join(self.settings_dir, self.prjid, 'PrintDraft')
            fdir = os.path.join(self.settings_dir, self.prjid, 'shared', 'fonts')
            if os.path.exists(fdir):
                cachepath(fdir)
            readConfig = True
        self.userconfig.set("init", "project", self.prjid)
        if readConfig or self.configId != configName:
            if configName == "Default":
                self._copyConfig(None, configName, moving=True)
            if currprj != self.prjid:
                self._copyConfig("Default", configName)
            else:
                self._copyConfig(self.configId, configName)
            res = self.readConfig(cfgname=configName)
            if res or forceConfig:
                self.configId = configName
                if self.configId is not None and len(self.configId):
                    self.userconfig.set("init", "config", self.configId)
            return res
        else:
            return True

    def getDialogTitle(self):
        prjid = self.get("fcb_project")
        if prjid is None:
            return _("PTXprint {} - Bible Layout for Everyone!     Start by selecting a project to work with...").format(VersionStr)
        else:
            if self.get('r_book') == "multiple":
                bks = self.get('t_booklist').split()
            else:
                bks = [self.get('ecb_book')]
                
            if len(bks) == 2:
                bks = bks[0] + "," + bks[1]
            elif len(bks) <= 4:
                bks = ",".join(bks)
            elif len(bks) > 4:
                bks = bks[0] + "," + bks[1] + "..." + bks[-2] + "," + bks[-1]
            else:
                try:
                    bks = bks[0]
                except IndexError:
                    bks = _("No book selected!")
            return "PTXprint {}   -  {} ({}) {}".format(VersionStr, prjid, bks, self.get("ecb_savedConfig") or "")

    def configName(self):
        return self.configId or None

    def configPath(self, cfgname=None, prjid=None, makePath=False):
        if prjid is None:
            prjid = self.prjid
        if self.settings_dir is None or prjid is None:
            return None
        prjdir = os.path.join(self.settings_dir, prjid, "shared", "ptxprint")
        if cfgname is not None and len(cfgname):
            prjdir = os.path.join(prjdir, cfgname)
        if makePath:
            os.makedirs(prjdir,exist_ok=True)
        return prjdir

    def readConfig(self, cfgname=None):
        if cfgname is None:
            cfgname = self.configName() or ""
        path = os.path.join(self.configPath(cfgname), "ptxprint.cfg")
        if not os.path.exists(path):
            return False
        #print("Reading config: {}".format(path))
        config = configparser.ConfigParser()
        config.read(path, encoding="utf-8")
        self.versionFwdConfig(config)
        self.loadConfig(config)
        return True

    def writeConfig(self, cfgname=None):
        if cfgname is None:
            cfgname = self.configName() or ""
        path = os.path.join(self.configPath(cfgname=cfgname, makePath=True), "ptxprint.cfg")
        config = self.createConfig()
        #print("Writing config: {}".format(path))
        with open(path, "w", encoding="utf-8") as outf:
            config.write(outf)

    def _configset(self, config, key, value):
        if "/" in key:
            (sect, k) = key.split("/", maxsplit=1)
        else:
            (sect, k) = (key, "")
        if not config.has_section(sect):
            config.add_section(sect)
        if isinstance(value, bool):
            value = "true" if value else "false"
        config.set(sect, k, value)

    def createConfig(self):
        def sortkeys(x):
            k, v = x
            if k in self._activekeys:
                return (0, k, v)
            else:
                return (1, k, v)
        config = configparser.ConfigParser()
        for k, v in sorted(ModelMap.items(), key=sortkeys):
            if v[0] is None or k.endswith("_"):
                continue
            if k in self._attributes:
                v = self._attributes[k]
                val = getattr(self, v[0])
                if val is None:
                    continue
                if v[1]:
                    val = "\n".join(x.withvars(self) for x in val)
                else:
                    val = val.withvars(self)
            elif v[0].startswith("bl_"):
                val = self.get(v[0])
                self._configset(config, k+"/name", val[0] or "")
                self._configset(config, k+"/style", val[1] or "")
                continue
            else:
                if v[0] is None:
                    continue
                val = self.get(v[0], asstr=True)
            if k in self._settingmappings:
                if val == "" or val == self.ptsettings.dict.get(self._settingmappings[k], ""):
                    continue
            self._configset(config, k, str(val) if val is not None else "")
        return config

    def _config_get(self, config, section, option, conv=None, fallback=_UNSET, **kw):
        try:
            v = config.get(section, option, **kw)
        except (NoSectionError, NoOptionError):
            if fallback is _UNSET:
                raise
            return fallback
        if conv is None:
            return v
        if v == "" and fallback is not _UNSET:
            return fallback
        return conv(v)

    def versionFwdConfig(self, config):
        version = self._config_get(config, "config", "version", conv=float, fallback=0.0)
        # print("version=",version)
        v = float(version)
        if v < 0.9:
            try:
                self._configset(config, "document/ifshowchapternums", not config.getboolean("document", "ifomitchapternum"))
                self._configset(config, "document/ifshowversenums", not config.getboolean("document", "ifomitallverses"))
                self._configset(config, "document/bookintro", not config.getboolean("document", "supressbookintro"))
                self._configset(config, "document/introoutline", not config.getboolean("document", "supressintrooutline"))
                self._configset(config, "document/firstparaindent", not config.getboolean("document", "supressindent"))
                self._configset(config, "document/sectionheads", not config.getboolean("document", "supresssectheads"))
                self._configset(config, "document/parallelrefs", not config.getboolean("document", "supressparallels"))
            except:
                pass
        if v < 1.2:
            bl = self._config_get(config, "project", "booklist")
            self._configset(config, "project/bookscope", "multiple" if len(bl) else "single")
        if v < 1.201:
            cnfname = self.configName()
            for d in ('PicLists', 'AdjLists'):
                p = os.path.join(self.configPath(cnfname), d)
                for f in os.listdir(p):
                    if "-draft" in f:
                        newf = os.path.join(f.replace("-draft", "-"+cnfname))
                        if not os.path.exists(newf):
                            move(os.path.join(p, f), newf)
            config.set("config", "version", "1.201")

    def loadConfig(self, config):
        def setv(k, v): self.set(k, v, skipmissing=True)
        for sect in config.sections():
            for opt in config.options(sect):
                key = "{}/{}".format(sect, opt)
                val = config.get(sect, opt)
                if key in ModelMap:
                    # print("Key:", key)
                    v = ModelMap[key]
                    if val == "None":
                        val = None
                    if key in self._attributes:
                        w = self._attributes[key]
                        if w[1]:
                            val = val.split("\n") if val is not None else []
                            val = [Path(x, self) for x in val if x is not None]
                            if w[2] is not None:
                                setv(w[2], ",".join(pdfre.sub(r"\1", x.as_posix()) for x in val))
                        else:
                            val = Path(val, self) if val is not None else None
                            if w[2] is not None and val is not None:
                                setv(w[2], pdfre.sub(r"\1", val.as_posix()))
                        setattr(self, w[0], val)
                    else:
                        try: # Safeguarding from changed/missing keys in .cfg  or v[0].startswith("f_") 
                            if v[0].startswith("s_"):
                                # print(key,v[0])
                                val = float(val) if val is not None and val != '' else 0
                            elif v[0].startswith("c_"):
                                # print("v[0]:", v[0])
                                val = config.getboolean(sect, opt) if val else False
                            if val is not None:
                                setv(v[0], val)
                        except AttributeError:
                            pass # ignore missing keys 
                elif sect in ModelMap:
                    v = ModelMap[sect]
                    if v[0].startswith("bl_") and opt == "name":
                        vname = re.sub(r"\s*,?\s+\d+\s*$", "", val) # strip legacy style and size
                        vstyle = config.get(sect, "style", fallback="")
                        # print("loadConfig: {}->{} = {},{}".format(sect, ModelMap[sect][0], vname, vstyle))
                        setv(ModelMap[sect][0], (vname, vstyle))
                if key in self._activekeys:
                    getattr(self, self._activekeys[key])()
        for k, v in self._settingmappings.items():
            (sect, name) = k.split("/")
            try:
                val = config.get(sect, name)
            except configparser.NoOptionError:
                setv(ModelMap[k][0], self.ptsettings.dict.get(v, ""))
        if self.get("c_thumbtabs"):
            self.updateThumbLines()
        #self.customFolder = self.get("btn_selectOutputFolder")
        #if not self.get("c_useprintdraftfolder") and self.customFolder is not None and len(self.customFolder):
        #    self.working_dir = self.customFolder
        #    self.fixed_wd = True
        #else:
        #    self.working_dir = os.path.join(self.settings_dir, self.prjid, "PrintDraft")
        #    self.fixed_wd = False

    def editFile_delayed(self, *a):
        pass

    def generateNProcPicLists(self, bk, outdir, processor, priority="Both", sfmonly="piclist", isTemp=False, output=True):
        picposns = { "L": {"col":  ("tl", "bl"),             "span": ("t")},
                     "R": {"col":  ("tr", "br"),             "span": ("b")},
                     "":  {"col":  ("tl", "tr", "bl", "br"), "span": ("t", "b")}}
        srcfkey = 'src path'
        randomizePosn = self.get("c_randomPicPosn")
        diglotPrinter = None
        if self.get("c_diglot"):
            diglotPrinter = self.createDiglotView()
            diglotPics = {}
        self.setDate()  # update date/time to now
        if not os.path.exists(outdir):
            os.makedirs(outdir)

        # Assemble a list of figures and their sources
        picinfos = None
        if diglotPrinter is not None:
            diglotPics = None
            if isTemp and sfmonly != "sfm":      # only merge if source doesn't have L/R
                tmppics = self._getFigures(bk)
                if any(x[3] in "LR" for x in tmppics.keys()):
                    picinfos = tmppics
            if picinfos is None:
                if priority == "Both" or priority =="Pri ":
                    picinfos = self._getFigures(bk, suffix="L", sfmonly=sfmonly, usepiclists=not output)
                if priority == "Sec ":
                    picinfos = diglotPrinter._getFigures(bk, suffix="R", sfmonly=sfmonly, usepiclists=not output)
                if priority == "Both":
                    diglotPics = diglotPrinter._getFigures(bk, suffix="R", sfmonly=sfmonly, usepiclists=not output)
        else:
            picinfos = self._getFigures(bk, sfmonly=sfmonly)
        self.getFigureSources(picinfos, key=srcfkey)
        if diglotPrinter is not None and diglotPics is not None:
            diglotPrinter.getFigureSources(diglotPics, key=srcfkey)
            picinfos.update(diglotPics)
        # Copy them
        missingPics = []
        for k, v in picinfos.items():
            nB = newBase(v['src'])
            if srcfkey not in v:
                missingPics.append(v['src'])
                continue
            fpath = v[srcfkey]
            origExt = os.path.splitext(fpath)[1]
            v['dest file'] = processor(v, v[srcfkey], nB+origExt.lower())

        missingPicList = []
        extOrder = self.getExtOrder()
        plfname = self.getDraftFilename(bk)
        # Now write out the new PicList to a temp folder
        piclstfname = os.path.join(self.configPath(cfgname=self.configId, makePath=False), "PicLists", plfname)
        isdblcol = self.get("c_doublecolumn")
        ishiderefs = self.get("c_fighiderefs")
        lines = []
        if not len(picinfos):
            return ({}, [])
        for k, v in sorted(picinfos.items(),
                           key=lambda x: refKey(x[0][:3]+x[0][4:], info=x[0][3])):
            picposn = picposns[k[3] if diglotPrinter is not None else ""]
            if 'dest file' not in v:
                missingPics.append(v['src'])
                continue
            if 'media' in v and len(v['media']) and 'p' not in v['media']:
                continue
            if not isdblcol: # Single Column layout so change all tl+tr > t and bl+br > b
                if 'pgpos' in v:
                    v['pgpos'] = re.sub(r"([tb])[lr]", r"\1", v['pgpos'])
                else:
                    v['pgpos'] = "t"
            if 'pgpos' not in v:
                if not isTemp and randomizePosn:
                    v['pgpos'] = random.choice(picposn.get(v['size'], 'col')) # Randomize location of illustrations on the page (tl,tr,bl,br)
                else:
                    v['pgpos'] = picposn.get(v['size'], 'col')[0]
            if 'ref' in v and ishiderefs:
                del v['ref']
            v['src'] = os.path.basename(v['dest file'])
        if output:
            piclstfname = os.path.join(outdir, plfname)
            self._outPicInfo(picinfos, piclstfname, isTemp=isTemp)
        return (picinfos, missingPics)

    def _outPicInfo(self, picinfo, fpath, isTemp=True):
        lines = []
        if isTemp:
            lines.append(_("% TEMPORARY PicList: ({}) - DO NOT EDIT\n\n").format(self.get("_date")))
        else:
            lines.append(_("% PicList Generated by PTXprint: {}\n\n").format(self.get("_date")))
        for k, v in sorted(picinfo.items(),
                           key=lambda x: refKey(x[0][:3]+x[0][4:], info=x[0][3])):
            lines.append("{} {}|".format(k, v['caption']) + " ".join('{}="{}"'.format(x, v[x]) for x in pos3parms if x in v and v[x]))
        if not isTemp:
            lines.append(_("""
            
% Tips for PicLists:
%   a) If illustrations don't appear in PDF, check the anchor reference (start of each line):
%      (i) only use '.' as the ch.vs separator
%      (ii) anchor refs must match the text itself and be in logical ch.vs order
%   b) Delete the line to remove an illustration (or prefix with a % to skip over it)
%   c) In single-column layout no difference will be seen between 'span' and 'col'
%   d) To scale an image use the notation: size="span*.7" or size="col*1.3" (for 70% and 130%)
"""))
        dat = "\n".join(lines)+"\n"
        with open(fpath, "w", encoding="utf-8") as outf:
            outf.write(dat)

    def generatePicLists(self, booklist, priority="Both", generateMissingLists=False, output=True):
        xl = []
        outdir = self.configPath(cfgname=self.configName())
        if outdir is None:
            return {}
        outdir = os.path.join(outdir, "PicLists")
        existingList = []
        existingFilelist = []
        if output:
            for bk in booklist:
                outfname = os.path.join(outdir, self.getDraftFilename(bk))
                if os.path.exists(outfname) and os.path.getsize(outfname) != 0:
                    existingFilelist.append(os.path.basename(outfname))
                    existingList.append(bk)
            if len(existingFilelist) and not generateMissingLists:
                q1 = _("One or more PicList file(s) already exist!")
                q2 = "\n".join(existingFilelist)+_("\n\nDo you want to OVERWRITE the above-listed file(s)?")
                if self.msgQuestion(q1, q2):
                    existingList = []
        bks = list(set(booklist) - set(existingList))
        def procbk(pic, src, tgt):
            return pic['src']
        missingPics = []
        picinfos = {}
        for bk in bks:
            (pi, mps) = self.generateNProcPicLists(bk, outdir, procbk, sfmonly=("sfm" if output else "piclist"), priority=priority, output=output)
            missingPics.extend(mps)
            picinfos.update(pi) # ({"{} {}".format(bk, k): v for k,v in pi.items()})
        return picinfos

    def savePicLists(self, picinfo):
        bks = self.getBooks()
        for bk in bks:
            picitems = {k: v for k, v in picinfo.items() if k.startswith(bk + " ")}
            if not len(picitems):
                continue
            fname = self.getDraftFilename(bk)
            fdir = os.path.join(self.configPath(cfgname=self.configName()), "PicLists")
            if not os.path.exists(fdir):
                os.makedirs(fdir)
            fpath = os.path.join(fdir, fname)
            self._outPicInfo(picitems, fpath, isTemp=False)

    def getDraftFilename(self, bk, ext=".piclist"):
        fname = self.getBookFilename(bk, self.prjid)
        cname = "-" + (self.configName() or "Default")
        doti = fname.rfind(".")
        res = fname[:doti] + cname + fname[doti:] + ext if doti > 0 else fname + cname + ext
        return res

    def _fixPicinfo(self, vals):
        p = vals['pgpos']
        if all(x in "apw" for x in p):
            vals['media'] = p
            del vals['pgpos']
        elif re.match(r"^[tbhpc][lrc]?[0-9]?$", p):
            vals['media'] = 'p'
        else:
            vals['loc'] = p
            del vals['pgpos']
        p = vals['size']
        m = re.match(r"(col|span|page|full)(?:\*(\d+(?:\.\d*)))?$", p)
        if m:
            vals['size'] = m[1]
            if m[2] is not None and len(m[2]):
                vals['scale'] = m[2]
        return vals

    def _getFigures(self, bk, suffix="", sfmonly="piclist", media=None, usepiclists=False):
        res = {}
        fname = self.getBookFilename(bk, self.prjid)
        usepiclist = usepiclists or (sfmonly != "sfm" and self.get("c_usePicList")) # and bk not in TexModel._peripheralBooks
        if usepiclist:
            plfname = self.getDraftFilename(bk)
            piclstfname = os.path.join(self.configPath(cfgname=self.configName()), "PicLists", plfname)
            if not os.path.exists(piclstfname):
                # print("Can't find {}".format(piclstfname))
                usepiclist = False
            else:
                fname = piclstfname
        if not usepiclist:      # since possibly set false in above if
            fname = os.path.join(self.settings_dir, self.prjid, fname)
        if not os.path.exists(fname):
            return res
        elif usepiclist:
            with universalopen(fname) as inf:
                for l in (x.strip() for x in inf.readlines()):
                    if not len(l) or l.startswith("%"):
                        continue
                    m = l.split("|")
                    r = m[0].split(maxsplit=2)
                    if suffix == "":
                        k = "{} {}".format(r[0], r[1])
                    else:
                        k = "{}{} {}".format(r[0][:3], suffix, r[1])
                    res[k] = {'caption': r[2] if len(r) > 2 else ""}
                    if len(m) > 6:
                        for i, f in enumerate(m[1:]):
                            res[k][posparms[i+1]] = f
                        self._fixPicinfo(res[k])
                    else:
                        for d in re.findall(r'(\S+)\s*=\s*"([^"]+)"', m[-1]):
                            res[k][d[0]] = d[1]
                    # print(res[k])
        elif sfmonly != "piclist":
            with universalopen(fname) as inf:
                dat = inf.read()
                blocks = ["0"] + re.split(r"\\c\s+(\d+)", dat)
                for c, t in zip(blocks[0::2], blocks[1::2]):
                    m = re.findall(r"(?ms)(?<=\\v )(\d+?[abc]?([,-]\d+?[abc]?)?) (.(?!\\v ))*\\fig (.*?)\|(.+?\.....?)\|(....?)\|([^\\]+?)?\|([^\\]+?)?\|([^\\]+?)?\|([^\\]+?)?\\fig\*", t)
                    if len(m):
                        for f in m:     # usfm 2
                            r = "{}{} {}.{}".format(bk, suffix, c, f[0])
                            res[r] = {}
                            res[r] = {'caption':f[8].strip()}
                            res[r]['anchor'] = "{}.{}".format(c, f[0])
                            for i, v in enumerate(f[3:]):
                                res[r][posparms[i]] = v
                            self._fixPicinfo(res[r])
                    elif bk in TexModel._peripheralBooks:
                        m = re.findall(r"(?ms)\\fig (.*?)\|(.+?\.....?)\|(col|span)[^|]*\|([^\\]+?)?\\fig\*", dat)
                        if len(m):
                            for i, f in enumerate(m):
                                r = "{}{} 1.{}".format(bk, suffix, i)
                                res[r] = {}
                                res[r] = {'caption':f[0].strip()}
                                res[r]['src'] = f[1]
                                res[r]['size'] = f[2]
                                res[r]['anchor'] = "1.{}".format(i)
                                # self._fixPicinfo(res[r])
                    m = re.findall(r'(?ms)(?<=\\v )(\d+?[abc]?([,-]\d+?[abc]?)?) (.(?!\\v ))*\\fig ([^\\]*?)\|([^\\]+)\\fig\*', t)
                    if len(m):
                        for f in m:     # usfm 3
                            if "|" in f[4]:
                                break
                            r = "{}{} {}.{}".format(bk, suffix, c, f[0])
                            res[r] = {'caption':f[3].strip()}
                            res[r]['anchor'] = "{}.{}".format(c, f[0])
                            labelParams = re.findall(r'([a-z]+?="[^\\]+?")', f[4])
                            for l in labelParams:
                                k,v = l.split("=")
                                res[r][k.strip()] = v.strip('"')
                    elif bk in TexModel._peripheralBooks:
                        pass
                        # TO DO: Need to do something similar to what is above (but for USFM3 inline)
                    if media is not None and r in res:
                        if 'media' in res[r] and not any(x in media for x in res[r]['media']):
                            del res[r]
        return res

    def _sortkey(self, c, v):
        return "{:0>3}{:0>3}".format(c, re.sub(r"(\d+)[\-,abc\d]*", r"\1", v or "0"))

    def getFigureSources(self, figinfos, filt=newBase, key='src path'):
        ''' Add source filename information to each figinfo, stored with the key '''
        res = {}
        newfigs = {}
        for k, f in figinfos.items():
            newk = filt(f['src']) if filt is not None else f['src']
            newfigs.setdefault(newk, []).append(k)
        if self.get("c_useCustomFolder"):
            srchlist = [self.customFigFolder]
        else:
            srchlist = []
            if sys.platform == "win32":
                srchlist += [os.path.join(self.settings_dir, self.prjid, "figures")]
                srchlist += [os.path.join(self.settings_dir, self.prjid, "local", "figures")]
            elif sys.platform == "linux":
                chkpaths = []
                for d in ("local", "figures"):
                    chkpaths += [os.path.join(self.settings_dir, self.prjid, x) for x in (d, d.title())]
                for p in chkpaths:
                    if os.path.exists(p):
                        srchlist += [p]
        extensions = []
        extdflt = {x:i for i, x in enumerate(["jpg", "jpeg", "png", "tif", "tiff", "bmp", "pdf"])}
        imgord = self.get("t_imageTypeOrder").lower()
        extuser = re.sub("[ ,;/><]"," ",imgord).split()
        extensions = {x:i for i, x in enumerate(extuser) if x in extdflt}
        if not len(extensions):   # If the user hasn't defined any extensions 
            extensions = extdflt  # then we can assign defaults

        for srchdir in srchlist:
            if srchdir is None or not os.path.exists(srchdir):
                continue
            if self.get("c_exclusiveFiguresFolder"):
                search = [(srchdir, [], os.listdir(srchdir))]
            else:
                search = os.walk(srchdir)
            for subdir, dirs, files in search:
                for f in files:
                    doti = f.rfind(".")
                    origExt = f[doti:].lower()
                    if origExt[1:] not in extensions:
                        continue
                    filepath = os.path.join(subdir, f)
                    nB = filt(f) if filt is not None else f
                    if nB not in newfigs:
                        continue
                    for k in newfigs[nB]:
                        if key in figinfos[k]:
                            old = extensions.get(os.path.splitext(figinfos[k][key])[1].lower(), 10000)
                            new = extensions.get(os.path.splitext(filepath)[1].lower(), 10000)
                            if old > new:
                                figinfos[k][key] = filepath
                            elif old == new and (self.get("c_useLowResPics") \
                                                != bool(os.path.getsize(figinfos[k][key]) < os.path.getsize(filepath))):
                                figinfos[k][key] = filepath
                        else:
                            figinfos[k][key] = filepath

    def generateAdjList(self):
        existingFilelist = []
        booklist = self.getBooks()
        diglot  = self.get("c_diglot")
        # digmode = self.get("fcb_diglotPicListSources") if diglot else "Primary"
        prjid = self.get("fcb_project")
        secprjid = ""
        if diglot:
            secprjid = self.get("fcb_diglotSecProject")
            if secprjid is not None:
                secprjdir = os.path.join(self.settings_dir, secprjid)
            else:
                self.doError(_("No Secondary Project Set"), secondary=_("In order to generate an AdjList for Diglots, the \n"+
                                                                    "Secondary project must be set on the Diglot+Border tab."))
                return
        prjdir = os.path.join(self.settings_dir, self.prjid)
        for bk in booklist:
            fname = self.getDraftFilename(bk, ext=".adj")
            outfname = os.path.join(self.configPath(self.configName()), "AdjLists", fname)
            if os.path.exists(outfname):
                existingFilelist.append(re.split(r"\\|/",outfname)[-1])
        if len(existingFilelist):
            q1 = _("One or more Paragraph Adjust file(s) already exist!")
            q2 = "\n".join(existingFilelist)+_("\n\nDo you want to OVERWRITE the above-listed file(s)?")
            if not self.msgQuestion(q1, q2):
                return
        for bk in booklist:
            tmplist = []
            fname = self.getBookFilename(bk)
            outfname = os.path.join(self.configPath(self.configName()),
                                    "AdjLists", self.getDraftFilename(bk, ext=".adj"))
            adjlist = []
            flist = [os.path.join(prjdir, fname)]
            if diglot: 
                secfname = self.getBookFilename(bk, secprjid)
                flist += [os.path.join(secprjdir, secfname)]
            if len(flist) == 2:
                sfx = 'L'
            else:
                sfx = ""
            for infname in flist:
                if len(flist) == 2 and infname == flist[1]:
                    sfx = 'R'
                with open(infname, "r", encoding="utf-8") as inf:
                    dat = inf.read()
                    # It would be good to make this more inclusive (\p \m \q1 \q2 etc.) 
                    # and also include \s Section Heads as comments to help show whichs paragraphs are within a single section
                    m = re.findall(r"\\p ?\r?\n\\v (\S+)",dat)
                    if m is not None:
                        prv = 0
                        ch = 1
                        for v in m:
                            iv = int(re.sub(r"^(\d+).*?$", r"\1", v), 10)
                            if iv < prv:
                                ch = ch + 1
                            srtchvs = "{:0>3}{:0>3}{}".format(ch,v,sfx)
                            tmplist.append(srtchvs+"\u0009"+bk+sfx+" "+str(ch)+"."+v+" +0")
                            prv = iv
            if len(tmplist):
                for al in sorted(tmplist):
                    adjlist.append(al.split("\u0009")[1]+"\n")
            adjpath = os.path.join(self.configPath(self.configName()), "AdjLists")
            os.makedirs(adjpath, exist_ok=True)
            with open(outfname, "w", encoding="utf-8") as outf:
                outf.write("".join(adjlist))

    def generateHyphenationFile(self):
        listlimit = 27836 # 32749
        prjid = self.get("fcb_project") # self.dict['project/id']
        prjdir = os.path.join(self.settings_dir, self.prjid)
        infname = os.path.join(self.ptsettings.basedir, prjid, 'hyphenatedWords.txt')
        outfname = os.path.join(self.ptsettings.basedir, prjid, "shared", "ptxprint", 'hyphen-{}.tex'.format(prjid))
        hyphenatedWords = []
        if not os.path.exists(infname):
            m1 = _("Failed to Generate Hyphenation List")
            m2 = _("{} Paratext Project's Hyphenation file not found:\n{}").format(prjid, infname)
        else:
            m2b = ""
            m2c = ""
            z = 0
            with universalopen(infname) as inf:
                for l in inf.readlines()[8:]: # Skip over the Paratext header lines
                    l = l.strip().replace(u"\uFEFF", "")
                    l = re.sub(r"\*", "", l)
                    l = re.sub(r"=", "-", l)
                    # Paratext doesn't seem to allow segments of 1 character to be hyphenated  (for example: a-shame-d) 
                    # (so there's nothing to filter them out, because they don't seem to exist!)
                    if "-" in l:
                        if "\u200C" in l or "\u200D" in l or "'" in l: # Temporary workaround until we can figure out how
                            z += 1                                     # to allow ZWNJ and ZWJ to be included as letters.
                        elif re.search(r'\d', l):
                            pass
                        else:
                            if l[0] != "-":
                                hyphenatedWords.append(l)
            c = len(hyphenatedWords)
            if c >= listlimit:
                hyphwords = set([x.replace("-", "") for x in hyphenatedWords])
                sheets = usfmutils.load_stylesheets(self.getStylesheets())
                acc = {}
                for bk in self.getBooks():
                    f = os.path.join(self.prjdir, self.getBookFilename(bk, self.prjdir))
                    u = usfmutils.Usfm(f, stylesheets=sheets)
                    u.getwords(init=acc, constrain=hyphwords)
                if len(acc) >= listlimit:
                    shortlist = [k for k, v in sorted(acc.items(), key=lambda x:(-x[1], -len(x[0])))][:listlimit]
                else:
                    shortlist = sorted(acc.keys())
                m2b = "\n\nThat is too many for XeTeX! List truncated to longest {} words found in the active sources.".format(len(shortlist))
                hyphenatedWords = shortlist
            hyphenatedWords.sort(key = lambda s: s.casefold())
            outlist = '\\catcode"200C=11\n\\catcode"200D=11\n\\hyphenation{' + "\n".join(hyphenatedWords) + "}"
            with open(outfname, "w", encoding="utf-8") as outf:
                outf.write(outlist)
            if len(hyphenatedWords) > 1:
                m1 = _("Hyphenation List Generated")
                m2a = _("{} hyphenated words were gathered\nfrom Paratext's Hyphenation Word List.").format(c)
                if z > 0:
                    m2c = _("\n\nNote for Indic languages that {} words containing ZWJ").format(z) + \
                            _("\nand ZWNJ characters have been left off the hyphenation list.")
                m2 = m2a + m2b + m2c
            else:
                m1 = _("Hyphenation List was NOT Generated")
                m2 = _("No valid words were found in Paratext's Hyphenation List")
        self.doError(m1, m2)

    # def checkSFMforFancyIntroMarkers(self):
        # unfitBooks = []
        # prjid = self.get("fcb_project")
        # prjdir = os.path.join(self.settings_dir, prjid)
        # bks = self.getBooks()
        # for bk in bks:
            # if bk not in TexModel._peripheralBooks:
                # fname = self.getBookFilename(bk, prjid)
                # fpath = os.path.join(self.settings_dir, prjid, fname)
                # if os.path.exists(fpath):
                    # with open(fpath, "r", encoding="utf-8") as inf:
                        # sfmtxt = inf.read()
                    # # Put strict conditions on the format (including only valid \ior using 0-9, not \d digits from any script)
                    # # This was probably too restrictive, but is a great RegEx: \\ior ([0-9]+(:[0-9]+)?[-\u2013][0-9]+(:[0-9]+)?) ?\\ior\*
                    # if regex.search(r"\\iot .+\r?\n(\\io\d .+?\\ior [()0-9\-:.,\u2013\u2014 ]+?\\ior\* ?\r?\n)+\\c 1", sfmtxt, flags=regex.MULTILINE) \
                       # and len(regex.findall(r"\\iot",sfmtxt)) == 1: # Must have exactly 1 \iot per book 
                        # pass
                    # else:
                        # unfitBooks.append(bk)
        # return unfitBooks

    def onFindMissingCharsClicked(self, btn_findMissingChars):
        count = collections.Counter()
        prjid = self.get("fcb_project")
        prjdir = os.path.join(self.settings_dir, prjid)
        bks = self.getBooks()
        for bk in bks:
            fname = self.getBookFilename(bk, prjid)
            fpath = os.path.join(prjdir, fname)
            if os.path.exists(fpath):
                with open(fpath, "r", encoding="utf-8") as inf:
                    # Strip out all markers themselves, and English content fields
                    sfmtxt = inf.read()
                    sfmtxt = re.sub(r'\\id .+?\r?\n', '', sfmtxt)
                    sfmtxt = re.sub(r'\\rem .+?\r?\n', '', sfmtxt)
                    # throw out illustration markup, BUT keep the caption text (USFM2 + USFM3)
                    sfmtxt = re.sub(r'\\fig (.*\|){5}([^\\]+)?\|[^\\]+\\fig\*', '\2', sfmtxt) 
                    sfmtxt = re.sub(r'\\fig ([^\\]+)?\|.*src=[^\\]+\\fig\*', '\1', sfmtxt) 
                    sfmtxt = re.sub(r'\\[+a-z]+\d?\*? ?', '', sfmtxt) # remove all \sfm codes
                    sfmtxt = re.sub(r'[0-9]', '', sfmtxt) # remove all digits
                    bkcntr = collections.Counter(sfmtxt)
                    count += bkcntr
        # slist = sorted(count.items(), key=lambda pair: pair[0])
        f = TTFont(*self.get("bl_fontR"))
        allchars = ''.join([i[0] for i in count.items()])
        if self.get("fcb_glossaryMarkupStyle") == "with ⸤floor⸥ brackets":
            allchars += "\u2e24\u2e25"
        if self.get("fcb_glossaryMarkupStyle") == "with ⌊floor⌋ characters":
            allchars += "\u230a\u230b"
        if self.get("fcb_glossaryMarkupStyle") == "with ⌞corner⌟ characters":
            allchars += "\u231e\u231f"
        missing = f.testcmap(allchars)
        self.set("t_missingChars", ' '.join(missing))
        return missing

    def onFontExtraRclicked(self, bl_fontExtraR):
        self.getFontNameFace("bl_fontExtraR")
        finfor = self.get('bl_fontR')
        finfoe = self.get('bl_fontExtraR')
        if finfor[0] == finfoe[0]:
            self.doError(_("The Fallback Font needs to be something other than the Regular Font."),
                         _("Please select a different Font."))
        else:
            f = TTFont(*finfoe)
            msngchars = self.get("t_missingChars") # .split(" ")
            msngchars = spclChars = re.sub(r"\\[uU]([0-9a-fA-F]{4,6})", lambda m:chr(int(m.group(1), 16)), msngchars)
            stillmissing = f.testcmap(msngchars)
            if len(stillmissing):
                self.doError(_("The Fallback Font just selected does NOT support all the missing characters listed."),
                             _("Please select a different Font."))

    def getExtOrder(self):
        # If the preferred image type(s) has(have) been specified, parse that string
        imgord = self.get("t_imageTypeOrder").lower()
        extOrder = re.sub("[ ,;/><]"," ",imgord).split()
        if not len(extOrder): # If the user hasn't defined a specific order then we can assign this
            if self.get("c_useLowResPics"): # based on whether they prefer small/compressed image formats
                extOrder = ["jpg", "jpeg", "png", "tif", "tiff", "bmp", "pdf"] 
            else:                              # or prefer larger high quality uncompressed image formats
                extOrder = ["pdf", "bmp", "tiff", "tif", "png", "jpeg", "jpg"] # reverse order
        return extOrder

    def finished(self):
        pass

    def incrementProgress(self, val=None):
        pass

    def getStyleSheets(self, generated=False):
        res = []
        cpath = self.configPath(cfgname=self.configName())
        rcpath = self.configPath("")
        res.append(os.path.join(self.scriptsdir, "ptx2pdf.sty"))
        if self.get('c_useCustomSty'):
            res.append(os.path.join(self.settings_dir, self.prjid, "custom.sty"))
        if self.get('c_useModsSty'):
            for p in (cpath, rcpath):
                fp = os.path.join(p, "ptxprint-mods.sty")
                if os.path.exists(fp):
                    res.append(fp)
                    break
        if generated:
            for p in (cpath, rcpath):
                fp = os.path.join(p, "NestedStyles.sty")
                if os.path.exists(fp):
                    res.append(fp)
                    break
        return res

    def _getArchiveFiles(self, books, prjid=None, cfgid=None):
        sfiles = {'c_useCustomSty': ("custom.sty", False),
                  'c_useModsSty': ("ptxprint-mods.sty", True),
                  'c_useModsTex': ("ptxprint-mods.tex", True),
                  'c_usePrintDraftChanges': ("PrintDraftChanges.txt", False)}
        res = {}
        cfgchanges = {}
        pictures = set()
        if prjid is None:
            prjid = self.prjid
        if cfgid is None:
            cfgid = self.configName()
        cfpath = "shared/ptxprint/"
        if cfgid is not None:
            cfpath += cfgid+"/"
        basecfpath = self.configPath(cfgname=cfgid, prjid=prjid)

        # pictures and texts
        picinfos = {}
        for bk in books:
            fname = self.getBookFilename(bk, prjid)
            fpath = os.path.join(self.settings_dir, prjid)
            res[os.path.join(fpath, fname)] = fname
            picinfos.update(self.getFigures(bk))
        self.getFigureSources(picinfos)
        pathkey = 'src path'
        for f in (p[pathkey] for p in picinfos.values() if pathkey in p):
                res[f] = "figures/"+os.path.basename(f)

        # adjlists
        adjpath = os.path.join(basecfpath, "AdjLists")
        adjbks = set(self.getDraftFilename(bk, ext=".adj") for x in books)
        if os.path.exists(adjpath):
            for adj in os.listdir(adjpath):
                if adj.endswith(".adj") and adj in adjbks:
                    res[os.path.join(adjpath, adj)] = cfpath+"AdjLists/"+adj

        # piclists
        piclstpath = os.path.join(basecfpath, "PicLists")
        picbks = set(self.getDraftFilename(bk) for x in books)
        if os.path.exists(piclstpath):
            for pic in os.listdir(piclstpath):
                if pic.endswith(".piclist") and pic in picbks:
                    res[os.path.join(piclstpath, pic)] = cfpath+"PicLists/"+pic

        # fonts
        for k, v in TexModel._fonts.items():
            if v[1] is None or self.get(v[1]):
                font_info = self.get(v[0])
                f = TTFont(*font_info)
                fname = os.path.basename(f.filename)
                res[f.filename] = "shared/fonts/"+fname

        # config files
        for t, a in sfiles.items():
            if isinstance(t, str) and not self.get(t):
                continue
            if a[1]:
                s = os.path.join(basecfpath, a[0])
                d = cfpath + a[0]
            else:
                s = os.path.join(self.settings_dir, prjid, a[0])
                d = a[0]
            if os.path.exists(s):
                res[s] = d

        if self.get("c_useModsTex"):
            loaded = False
            if cfgid is not None:
                p = os.path.join(self.settings_dir, prjid, 'shared', 'ptxprint', cfgid, 'ptxprint-mods.tex')
                loaded = os.path.exists(p)
            if not loaded:
                p = os.path.join(self.settings_dir, prjid, 'shared', 'ptxprint', 'ptxprint-mods.tex')
                if os.path.exists(p):
                    res[p] = "shared/ptxprint/ptxprint-mods.tex"

        script = self.get("btn_selectScript")
        if script is not None and len(script):
            res[script] = os.path.basename(script)
            cfgchanges["btn_selectScript"] = os.path.join(self.settings_dir, prjid, os.path.basename(script))

        hyphenfpath = os.path.join(self.settings_dir, prjid, "shared", "ptxprint")
        hyphentpath = "shared/ptxprint/"
        hyphenfile = "hyphen-{}.tex".format(self.prjid)
        if os.path.exists(os.path.join(hyphenfpath, hyphenfile)):
            res[os.path.join(hyphenfpath, hyphenfile)] = hyphentpath + hyphenfile

        if self.ptsettings is None or self.prjid != prjid:
            self.ptsettings = ParatextSettings(self.settings_dir, prjid)
        ptres = self.ptsettings.getArchiveFiles()
        res.update(ptres)
        return (res, cfgchanges)

    def createDiglotView(self):
        prjid = self.get("fcb_diglotSecProject")
        cfgid = self.get("ecb_diglotSecConfig")
        digview = ViewModel(self.settings_dir, self.working_dir, self.userconfig, self.scriptsdir)
        digview.setPrjid(prjid)
        if cfgid is not None and cfgid != "":
            digview.setConfigId(cfgid)
        return digview

    def createArchive(self, filename=None):
        if filename is None:
            filename = os.path.join(self.configPath(self.configName()), "ptxprintArchive.zip")
        if not filename.lower().endswith(".zip"):
            filename += ".zip"
        zf = ZipFile(filename, mode="w", compression=ZIP_DEFLATED, compresslevel=9)
        zf.write(os.path.join(self.settings_dir, "usfm.sty"), "usfm.sty")
        self._archiveAdd(zf, self.getBooks())
        if self.get("c_diglot"):
            digview = self.createDiglotView()
            digview._archiveAdd(zf, self.getBooks())
        if self.get("c_archiveTemps"):
            prjdir = os.path.join(self.settings_dir, self.prjid)
            for f in self.tempFiles:
                outfname = os.path.relpath(f, prjdir)
                zf.write(f, outfname)
        zf.close()

    def _archiveAdd(self, zf, books):
        prjid = self.prjid
        cfgid = self.configName()
        entries, cfgchanges = self._getArchiveFiles(books, prjid=prjid, cfgid=cfgid)
        for k, v in entries.items():
            zf.write(k, arcname=prjid + "/" + v)
        tmpcfg = {}
        for k,v in cfgchanges.items():
            tmpcfg[k] = self.get(k)
            self.set(k, v)
        config = self.createConfig()
        configstr = StringIO()
        config.write(configstr)
        zf.writestr(prjid + "/shared/ptxprint/" + (cfgid + "/" if cfgid else "") + "ptxprint.cfg",
                    configstr.getvalue())
        configstr.close()
        for k, v in tmpcfg.items():
            self.set(k, v)

    def updateThumbLines(self):
        munits = float(self.get("s_margins"))
        unitConv = {'mm':1, 'cm':10, 'in':25.4, '"':25.4}
        m = re.match(r"^.*?,\s*([\d.]+)(\S+)\s*(?:.*|$)", self.get("ecb_pagesize"))
        if m:
            pageheight = float(m.group(1)) * unitConv.get(m.group(2), 1)
        else:
            pageheight = 210
        tfactor = float(self.get("s_topmarginfactor"))
        bfactor = float(self.get("s_bottommarginfactor"))
        tabsheight = pageheight - munits * (tfactor + bfactor)   # in mm
        tabsheight -= 20 * 25.4 / 72.27                          # from default \TabsStart + \TabsEnd (in pt)
        if self.get("c_thumbrotate"):
            tabheight = float(self.get("s_thumblength") or 10)
        else:
            tabheight = float(self.get("s_thumbheight") or 4)
        newnum = int(tabsheight / tabheight)
        self.set("s_thumbtabs", newnum)
