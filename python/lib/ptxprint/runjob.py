import os, sys, re, subprocess
from PIL import Image
from io import BytesIO as cStringIO
from shutil import copyfile, rmtree
from threading import Thread
from ptxprint.runner import call, checkoutput
from ptxprint.texmodel import TexModel
from ptxprint.ptsettings import ParatextSettings
from ptxprint.view import ViewModel, VersionStr, refKey
from ptxprint.font import getfontcache
from ptxprint.usfmerge import usfmerge
from ptxprint.utils import _, universalopen

_errmsghelp = {
"! TeX capacity exceeded, sorry":        _("Uh oh! You've pushed TeX too far! Try turning Hyphenation off, or contact support."),
"! Paratext stylesheet":                 _("Check if the stylesheet specified on the Advanced tab exists."),
"! Unable to load picture":              _("Check if picture file is located in 'Figures', 'local\\figures' or a\n" +\
                                           "specified folder. Also try the option 'Omit Missing Pictures'"),
"! Unable to load picture or PDF file":  _("Check if image/PDF file is available on the system.\n" +
                                           "If you have specified one or more Front/Back matter PDFs or a Watermark PDF\n" +
                                           "then ensure that the PDF(s) exist(s); OR uncheck those options (Advanced tab)."),
"! Missing control sequence inserted.":  _("Fallback font probably being applied to text in a footnote (not permitted!)"),
"! Missing number, treated as zero.":    _("Related to USFM3 illustration markup"),
"! Undefined control sequence.":         _("This might be related to a USFM marker error (using an unsupported marker).\n" +\
                                           "Try 'Run Basic Checks' in Paratext"),
"! Illegal unit of measure (pt inserted).":    _("One of the settings in the Stylesheet may be missing the units.\n" +\
                                           "To confirm that this is a stylesheet issue, temporarily turn off Stylesheets.\n" +\
                                           "Then, check any recent changes to the Stylesheets (on Advanced tab) and try again."),
"! File ended while scanning use of":    _("Try turning off PrintDraftChanges.txt and both Stylesheets on Advanced tab."),
"! Output loop---25 consecutive dead cycles.":  _("Sorry! XeTeX was unable to complete the typesetting.\n" +\
                                           "* If creating a Diglot, ensure both texts can print successfully\n" +\
                                           "  before merging them as a Diglot print. And ensure that there\n" +\
                                           "  aren't any large chunks of missing text in either of the projects.\n" +\
                                           "* Also check that you haven't inadvertently left certain settings on\n" +\
                                           "  from a previous session (Pictures, Diglot, Borders - which will show\n" +\
                                           "  in blue if these features are currently enabled)."),
"! Paratext stylesheet":                 _("Try turning off the ptxprint-mods stylesheet"),
"! File ended while scanning use of \iotableleader.": _("Problem with Formatting Intro Outline\n" +\
                                           "Try disabling option 'Right-Align \ior with tabbed leaders' on the Body tab"),
"! Emergency stop.":                     _("Probably a TeX macro problem - contact support, or post a bug report"),
"! Not a letter.":                       _("Possible fault in the hyphenation file\n" +\
                                           "Try turning off Hyphenate option located on the Body tab"),
"! Font \extrafont":                     _("Fallback Font issue - set a font on the Body tab.\n" +\
                                           "(Turn off the option 'Use Fallback Font' or specify a valid font)"),
"! Font":                                _("Font related issue. The most likely reason for this error is that\n" +\
                                          "the selected font has not been installed for all users. See FAQ."),
"! Too many }'s":                        _("Possibly a TeX macro issue - contact support, or post a bug report"),
"! This can't happen (page)":            _("Possibly a TeX macro issue - contact support, or post a bug report"),
"! I can't find file `paratext2.tex'.":  _("Possibly a faulty installation."),
"! I can't find file `ptx-tracing.tex'.": _("Possibly a faulty installation."),
"Runaway argument?":                     _("Unknown issue. Maybe related to Right-aligned tabbed leaders\n" +\
                                           "Try turning off PrintDraftChanges.txt and both Stylesheets"),
"Unknown":                               _("Sorry, there is no diagnostic help for this error.\n" +\
                                           "Ensure that the Basic Checks (in Paratext) pass for all books in list.\n" +\
                                           "Try turning off various settings, and disable Changes or Stylesheets.\n" +\
                                           "If peripheral books are selected, try excluding those.\n" +\
                                           "Sometimes just closing and re-opening PTXprint can make things work again!")
}
# \def\LineSpacingFactor{{{paragraph/linespacingfactor}}}
# \def\VerticalSpaceFactor{{1.0}}
# \baselineskip={paragraph/linespacing}pt {paragraph/varlinespacing} {paragraph/linemax} {paragraph/linemin}
# \XeTeXinterwordspaceshaping = {document/spacecntxtlztn}
# %\extrafont  %% This will be replaced by code for the fallback fonts to be used for special/missing characters

def base(fpath):
    doti = fpath.rfind(".")
    return os.path.basename(fpath[:doti])

# https://sites.google.com/a/lci-india.org/typesetting/home/illustrations/where-to-find-illustrations
def codeLower(fpath):
    cl = re.findall(r"(?i)_?((?=ab|cn|co|hk|lb|bk|ba|dy|gt|dh|mh|mn|wa|dn|ib)..\d{5})[abc]?$", base(fpath))
    if cl:
        return cl[0].lower()
    else:
        return ""

def newBase(fpath):
    clwr = codeLower(fpath)
    if len(clwr):
        return clwr
    else:
        return re.sub('[()&+,.;: ]', '_', base(fpath).lower())

_diglot = {
"ifusediglotcustomsty_":    "project/ifusecustomsty",
"ifusediglotmodsty_":       "project/ifusemodssty",
"ifdiglotincludefootnotes_":"notes/includefootnotes",
"ifdiglotincludexrefs_":    "notes/includexrefs",

"diglot/colorfonts" :       "document/ifcolorfonts",
"diglot/ifrtl" :            "document/ifrtl",
"diglot/ifomitsinglechnum": "document/ifomitsinglechnum",
"diglot/fontfactor" :       "paper/fontfactor",
"diglot/linespacingfactor": "paragraph/linespacingfactor",
"diglot/iflinebreakon" :    "document/iflinebreakon",
"diglot/linebreaklocale" :  "document/linebreaklocale",

"diglot/docscript" :        "document/script",
"diglot/docdigitmapping" :  "document/digitmapping",
                            
"diglot/fontregular" :      "document/fontregular",
"diglot/fontbold" :         "document/fontbold",
"diglot/fontitalic" :       "document/fontitalic",
"diglot/fontbolditalic" :   "document/fontbolditalic",
"diglot/ifshowversenums" :  "document/ifshowversenums",
"diglot/ifblendfnxr" :      "notes/ifblendfnxr",
"diglotfancy/versedecorator":       "fancy/versedecorator",
"diglotfancy/versedecoratorpdf":    "fancy/versedecoratorpdf",
"diglotfancy/versedecoratorshift":  "fancy/versedecoratorshift",
"diglotfancy/versedecoratorscale":  "fancy/versedecoratorscale",
"diglotfancy/sectionheader":    "fancy/sectionheader",
"diglotfancy/sectionheadershift":   "fancy/sectionheadershift",
"diglotfancy/sectionheaderscale":   "fancy/sectionheaderscale",
"diglotfancy/sectionheaderpdf": "fancy/sectionheaderpdf",
}

_joblock = None
def lockme(job):
    global _joblock
    if _joblock is not None:
        return False
    _joblock = job
    return True

def unlockme():
    global _joblock
    _joblock = None

def isLocked():
    global _joblock
    return _joblock is not None

class RunJob:
    def __init__(self, printer, scriptsdir, args, inArchive=False):
        self.scriptsdir = scriptsdir
        self.printer = printer
        self.tempFiles = []
        self.tmpdir = "."
        self.maxRuns = 1
        self.changes = None
        self.args = args
        self.res = 0
        self.thread = None
        self.busy = False
        self.ispdfxa = False
        self.inArchive = inArchive

    def doit(self):
        if not lockme(self):
            return False
        self.texfiles = []
        info = TexModel(self.printer, self.args.paratext, self.printer.ptsettings, self.printer.prjid, inArchive=self.inArchive)
        info.debug = self.args.debug
        self.tempFiles = []
        self.prjid = info.dict["project/id"]
        self.prjdir = os.path.join(self.args.paratext, self.prjid)
        if self.prjid is None or not len(self.prjid):     # can't print no project
            return
        self.tmpdir = os.path.join(self.prjdir, 'PrintDraft') if info.asBool("project/useprintdraftfolder") \
                                                                 or self.args.directory is None else self.args.directory
        os.makedirs(self.tmpdir, exist_ok=True)
        jobs = self.printer.getBooks(files=True)

        self.books = []
        self.maxRuns = 1 if self.printer.get("c_quickRun") else 5
        self.changes = None
        self.checkForMissingDecorations(info)
        info["document/piclistfile"] = ""
        if info.asBool("document/ifinclfigs"):
            self.gatherIllustrations(info, jobs, self.args.paratext)
            # self.texfiles += self.gatherIllustrations(info, jobs, self.args.paratext)
        self.ispdfxa = self.printer.get("c_PDFx1aOutput")
        
        if info.asBool("project/combinebooks"):
            joblist = [jobs]
        else:
            joblist = [[j] for j in jobs]

        if self.printer.diglotView is not None:
            digfraction = info.dict["document/diglotprifraction"]
            digprjid = info.dict["document/diglotsecprj"]
            digcfg = info.dict["document/diglotsecconfig"]
            digprjdir = os.path.join(self.args.paratext, digprjid)
            digptsettings = ParatextSettings(self.args.paratext, digprjid)
            diginfo = TexModel(self.printer.diglotView, self.args.paratext, digptsettings, digprjid)
            self.texfiles += sum((self.digdojob(j, info, diginfo, digprjid, digprjdir) for j in joblist), [])
        else: # Normal (non-diglot)
            self.texfiles += sum((self.dojob(j, info) for j in joblist), [])
        self.printer.tempFiles = self.texfiles  # Always do this now - regardless!

    def done_job(self, outfname, info):
        # Work out what the resulting PDF was called
        cfgname = info['config/name']
        if cfgname is not None and cfgname != "":
            cfgname = "-"+cfgname
        else:
            cfgname = ""
        pdfname = os.path.join(self.tmpdir, outfname.replace(".tex", ".pdf"))
        print(pdfname)
        if self.res == 0:
            if self.printer.isDisplay and os.path.exists(pdfname):
                if sys.platform == "win32":
                    os.startfile(pdfname)
                elif sys.platform == "linux":
                    subprocess.call(('xdg-open', pdfname))
                # Only delete the temp files if the PDF was created AND the user did NOT select to keep them

            if not self.args.print: # We don't want pop-up messages if running in command-line mode
                fname = os.path.join(self.tmpdir, pdfname.replace(".pdf", ".log"))
                if os.path.exists(fname):
                    with open(fname, "r", encoding="utf-8", errors="ignore") as logfile:
                        log = logfile.read() # unlike other places, we *do* want the entire log file
                    badpgs = re.findall(r'(?i)SOMETHING BAD HAPPENED on page (\d+)\.', "".join(log))
                    if len(badpgs):
                        print(_("Layout problems were encountered on page(s): ") + ", ".join(badpgs))
                        self.printer.doError(_("PDF was created BUT..."),
                            secondary=_("Layout problems were encountered on page(s): ") + ",".join(badpgs) + \
                                  _("\n\nTry changing the PicList and/or AdjList settings to solve issues."), \
                            title=_("PTXprint [{}] - Warning!").format(VersionStr),
                            threaded=True)

        elif not self.args.print: # We don't want pop-up messages if running in command-line mode
            finalLogLines = self.parseLogLines()
            self.printer.doError(_("Failed to create: ")+re.sub(r".+[\\/](.+\.pdf)",r"\1",pdfname),
                    secondary="".join(finalLogLines[-20:]), title="PTXprint [{}] - Error!".format(VersionStr),
                    threaded=True)
            self.printer.onIdle(self.printer.showLogFile)
        if len(self.rerunReasons):
            self.printer.set("l_statusLine", _("Rerun to fix: ") + ", ".join(self.rerunReasons))
        else:
            self.printer.set("l_statusLine", "")
        # if info.asBool("project/keeptempfiles"):
            # self.printer.tempFiles = self.texfiles
        # else:
            # self.removeTempFiles(self.texfiles)
        self.printer.finished()
        self.busy = False
        unlockme()

    def parselog(self, fname, rerunp=False, lines=20):
        loglines = []
        rerunres = False
        if not os.path.exists(fname):
            return (loglines, rerunres)
        try:
            with open(fname, "r", encoding="utf-8", errors="ignore") as logfile:
                for i, l in enumerate(logfile.readlines()):
                    if rerunp and l.startswith("PARLOC: Rerun."):
                        rerunres = True
                    loglines.append(l)
                    if len(loglines) > lines:
                        loglines.pop(0)
        except:
            loglines.append("Logfile missing: "+fname)
        return (loglines, rerunres)

    def readfile(self, fname):
        try:
            with open(fname, "r", encoding="utf-8") as inf:
                res = "".join(inf.readlines())
            return res
        except FileNotFoundError:
            return ""

    def parseLogLines(self):
        # it did NOT finish successfully, so help them troubleshoot what might have gone wrong:
        finalLogLines = self.loglines[-30:-10]
        foundmsg = False
        finalLogLines.append("-"*90+"\n")
        for l in finalLogLines:
            if l[:1] == "!" and not foundmsg:
                for m in sorted(_errmsghelp.keys(),key=len, reverse=True):
                    if m in l:
                        if l[:-1] != m:
                            finalLogLines.append("{}\n".format(m))
                        finalLogLines.append(_errmsghelp[m]+"\n")
                        foundmsg = True
                        break
        if not foundmsg:
            finalLogLines.append(_errmsghelp["Unknown"]+"\n")
        books = re.findall(r"\d\d(...){}.+?\....".format(self.prjid), "".join(finalLogLines))
        if len(books):
            book = " in {}".format(books[-1])
        else:
            book = ""
        refs = re.findall(r"([1-9]\d{0,2}[.:][1-9]\d{0,2}[^0-9])", "".join(finalLogLines))
        if len(refs):
            finalLogLines.append("\nReferences to check{}: {}".format(book, " ".join(refs)))

        texmrkrs = [r"\fi", "\if", "\ifx", "\\box", "\\hbox", "\\vbox", "\else", "\\book", "\\par",
                     "\\edef", "\\gdef", "\\dimen" "\\hsize", "\\relax"]
        allmrkrs = re.findall(r"(\\[a-z0-9]{0,5})[ *\r\n.]", "".join(finalLogLines[-8:]))
        mrkrs = [x for x in allmrkrs if x not in texmrkrs]
        if 0 < len(mrkrs) < 7:
            if "\ef" in mrkrs or "\ex" in mrkrs:
                finalLogLines.append("Sorry, Study Bible Markup (\ef \ex etc.) is not yet supported!")

        files = re.findall(r'(?i)([^\\/\n."= ]*?\.(?=jpg|jpeg|tif|tiff|bmp|png|pdf)....?)', "".join(finalLogLines))
        if len(files):
            finalLogLines.append("\nFile(s) to check: {}".format(", ".join(files)))
        return finalLogLines

    def dojob(self, jobs, info):
        donebooks = []
        for b in jobs:
            try:
                out = info.convertBook(b, self.tmpdir, self.prjdir)
            except FileNotFoundError as e:
                self.printer.doError(str(e))
                out = None
            if out is None:
                continue
            donebooks.append(out)
        if not len(donebooks):
            unlockme()
            return []
        self.books += donebooks
        info["project/bookids"] = jobs
        info["project/books"] = donebooks
        res = self.sharedjob(jobs, info)
        return [os.path.join(self.tmpdir, out)] + res

    def digdojob(self, jobs, info, diginfo, digprjid, digprjdir):
        texfiles = []
        donebooks = []
        digdonebooks = []
        _digSecSettings = ["paper/pagesize", "paper/height", "paper/width", "paper/margins",
                           "paper/topmarginfactor", "paper/bottommarginfactor",
                           "paper/headerposition", "paper/footerposition", "paper/ruleposition",
                           "document/ch1pagebreak", "document/bookintro", "document/introoutline", 
                           "document/parallelrefs", "document/elipsizemptyvs", "notes/iffootnoterule",
                           "notes/ifblendfnxr", "notes/includefootnotes", "notes/includexrefs", 
                           "notes/fneachnewline", "notes/xreachnewline", "document/filterglossary", 
                           "document/chapfrom", "document/chapto", "document/ifcolorfonts", "document/ifomitsinglechnum"]
        diginfo["project/bookids"] = jobs
        diginfo["project/books"] = digdonebooks
        diginfo["document/ifdiglot"] = "%"
        diginfo["footer/ftrcenter"] = "-empty-"
        diginfo["footer/ifftrtitlepagenum"] = "%"
        diginfo["fancy/pageborder"] = "%"
        diginfo["document/clsinglecol"] = False
        diginfo["snippets/diglot"] = False
        docdir = os.path.join(info["/ptxpath"], info["project/id"], "PrintDraft")
        for k in _digSecSettings:
            diginfo[k]=info[k]
        syntaxErrors = []
        for b in jobs:
            try:
                out = info.convertBook(b, self.tmpdir, self.prjdir)
                digout = diginfo.convertBook(b, self.tmpdir, digprjdir)
            except FileNotFoundError as e:
                self.printer.doError(str(e))
                out = None
            if out is None:
                continue
            else:
                donebooks.append(out)
            if digout is None:
                continue
            else:
                digdonebooks.append(digout)
            
            # Now merge the secondary text (right) into the primary text (left) 
            left = os.path.join(self.tmpdir, out)
            right = os.path.join(self.tmpdir, digout)
            outFile = re.sub(r"^([^.]*).(.*)$", r"\1-diglot.\2", left)
            logFile = os.path.join(self.tmpdir, "ptxprint-merge.log")

            sheetsa = info.printer.getStyleSheets()
            sheetsb = diginfo.printer.getStyleSheets()
            try:
                usfmerge(left, right, outFile, stylesheetsa=sheetsa, stylesheetsb=sheetsb)
            except SyntaxError as e:
                syntaxErrors.append("{} {} line: {}".format(self.prjid, b, str(e).split('line', maxsplit=1)[1]))
            except Exception as e:
                syntaxErrors.append("{} {} Error: {}".format(self.prjid, b, str(e)))
            for f in [left, right, outFile, logFile]:
                texfiles += [os.path.join(self.tmpdir, f)]

        if not len(donebooks) or not len(digdonebooks):
            unlockme()
            return []

        if len(syntaxErrors):
            self.printer.doError(_("Failed to merge texts due to a Syntax Error:"),
            secondary="\n".join(syntaxErrors)+_("\n\nIf original USFM text is correct, then check "+ \
                                                    "if PrintDraftChanges.txt has caused the error(s)."),
            title=_("PTXprint [{}] - Diglot Merge Error!").format(VersionStr))

        info["project/bookids"] = jobs
        info["project/books"] = donebooks
        self.books += digdonebooks

        # Pass all the needed parameters for the snippet from diginfo to info
        for k,v in _diglot.items():
            info[k]=diginfo[v]
        info["document/diglotcfgrpath"] = os.path.relpath(diginfo.printer.configPath(diginfo.printer.configName()), docdir).replace("\\","/")
        info["_isDiglot"] = True
        res = self.sharedjob(jobs, info, extra="-diglot")
        texfiles += res
        return texfiles

    def sharedjob(self, jobs, info, prjid=None, prjdir=None, extra=""):
        if prjid is None:
            prjid = self.prjid
        if prjdir is None:
            prjdir = self.prjdir
        cfgname = info['config/name']
        if cfgname is None or cfgname == "":
            cfgname = ""
        else:
            cfgname = "-" + cfgname
        outfname = info.printer.baseTeXPDFnames(jobs)[0] + ".tex"
        info.update()
        texfiledat = info.asTex(filedir=self.tmpdir, jobname=outfname.replace(".tex", ""), extra=extra)
        with open(os.path.join(self.tmpdir, outfname), "w", encoding="utf-8") as texf:
            texf.write(texfiledat)
        if self.inArchive:
            return [os.path.join(self.tmpdir, outfname.replace(".tex", x)) for x in (".tex", ".xdv")]
        os.putenv("hyph_size", "32749")     # always run with maximum hyphenated words size (xetex is still tiny ~200MB resident)
        os.putenv("stack_size", "32768")    # extra input stack space (up from 5000)
        ptxmacrospath = os.path.abspath(os.path.join(self.scriptsdir, "..", "..", "src"))
        if not os.path.exists(ptxmacrospath):
            for b in (getattr(sys, 'USER_BASE', '.'), sys.prefix):
                if b is None:
                    continue
                ptxmacrospath = os.path.abspath(os.path.join(b, 'ptx2pdf'))
                if os.path.exists(ptxmacrospath):
                    break

        pathjoin = (";" if sys.platform=="win32" else ":").join
        envtexinputs = os.getenv("TEXINPUTS")
        texinputs = [envtexinputs] if envtexinputs is not None and len(envtexinputs) else []
        texinputs += [os.path.abspath(self.tmpdir), ptxmacrospath]
        if sys.platform != "win32":
            texinputs += ["/usr/share/ptx2pdf/texmacros"]
        os.putenv('TEXINPUTS', pathjoin(texinputs))
        # print("TEXINPUTS=",os.getenv('TEXINPUTS'))
        miscfonts = getfontcache().fontpaths
        miscfonts.append(ptxmacrospath)
        miscfonts.append(os.path.join(prjdir, "shared"))
        if len(miscfonts):
            os.putenv("MISCFONTS", pathjoin(miscfonts))
        self.thread = Thread(target=self.run_xetex, args=(outfname, info))
        self.busy = True
        self.thread.start()
        return [os.path.join(self.tmpdir, outfname.replace(".tex", x)) for x in (".tex", ".xdv")]

    def wait(self):
        if self.busy:
            self.thread.join()
        return self.res

    def run_xetex(self, outfname, info):
        numruns = 0
        while numruns < self.maxRuns:
            self.printer.incrementProgress()
            if info["document/toc"] != "%":
                tocdata = self.readfile(os.path.join(self.tmpdir, outfname.replace(".tex", ".toc")))
            if info["document/includeimg"]:
                picdata = self.readfile(os.path.join(self.tmpdir, outfname.replace(".tex", ".picpages")))
            cmd = ["xetex", "-halt-on-error", "-interaction=nonstopmode", "-no-pdf"]
            runner = call(cmd + [outfname], cwd=self.tmpdir)
            if isinstance(runner, subprocess.Popen) and runner is not None:
                try:
                    runner.wait(self.args.timeout)
                except subprocess.TimeoutExpired:
                    print("Timed out!")
                self.res = runner.returncode
            else:
                self.res = runner
            print("cd {}; xetex {} -> {}".format(self.tmpdir, outfname, self.res))
            logfname = outfname.replace(".tex", ".log")
            (self.loglines, rerun) = self.parselog(os.path.join(self.tmpdir, logfname), rerunp=True, lines=300)
            info.printer.editFile_delayed(logfname, "wrk", "scroll_XeTeXlog", False)
            numruns += 1
            self.rerunReasons = []
            rererun = False
            if self.res:
                rererun = True
            if info["document/toc"] != "%":
                tocndata = self.readfile(os.path.join(self.tmpdir, outfname.replace(".tex", ".toc")))
                if tocdata != tocndata:
                    if numruns >= self.maxRuns:
                        self.rerunReasons.append(_("ToC pages"))
                    else:
                        print(_("Rerunning because the Table of Contents was updated"))
                        rererun = True
                else:
                    break
            if info["document/includeimg"]:
                picndata = self.readfile(os.path.join(self.tmpdir, outfname.replace(".tex", ".picpages")))
                if picdata != picndata:
                    self.rerunReasons.append(_("image copyrights"))
            if rerun:
                if numruns >= self.maxRuns:
                    self.rerunReasons.append(_("chapter numbers"))
                else:
                    print(_("Rerunning because inline chapter numbers moved"))
                    rererun = True
            if not rererun:
                break
        if not self.args.testing and not self.res:
            self.printer.incrementProgress()
            cmd = ["xdvipdfmx", "-E"]
            if self.printer.get("c_PDFx1aOutput"):
                cmd += ["-z", "0"]
            if self.args.extras & 1:
                cmd += ["-vv"]
            runner = call(cmd + [outfname.replace(".tex", ".xdv")], cwd=self.tmpdir)
            if self.args.extras & 1:
                print(f"Subprocess return value: {runner}")
            if isinstance(runner, subprocess.Popen) and runner is not None:
                try:
                    runner.wait(self.args.timeout)
                except subprocess.TimeoutExpired:
                    print("Timed out!")
                    self.res = runner.returncode
        print("Done")
        self.done_job(outfname, info)

    def checkForMissingDecorations(self, info):
        deco = {"pageborder" :     "Page Border",
                "sectionheader" :  "Section Heading",
                "endofbook" :      "End of Book",
                "versedecorator" : "Verse Number"}
        warnings = []
        if info.asBool("fancy/enableborders"):
            for k,v in deco.items():
                if info.asBool("fancy/"+k):
                    f = info.dict["fancy/{}pdf".format(k)] or ""
                    if not os.path.exists(f):
                        warnings += ["{} Decorator\n{}\n\n".format(v, f)]
            if len(warnings):
                self.printer.doError(_("Warning: Could not locate decorative PDF(s):"),
                        secondary="\n".join(warnings))

    def gatherIllustrations(self, info, jobs, ptfolder):
        picinfos = self.printer.picinfos
        pageRatios = self.usablePageRatios(info)
        tmpPicpath = os.path.join(self.printer.working_dir, "tmpPics")
        if not os.path.exists(tmpPicpath):
            os.makedirs(tmpPicpath)
        folderList = ["tmpPics", "tmpPicLists"] 
        #try:
        #    self.removeTmpFolders(self.printer.working_dir, folderList, mkdirs=True)
        #except PermissionError:
        #    print("Warning: Couldn't Remove Temporary Folders - is a temp file open?")
        cropme = info['document/iffigcrop']
        def carefulCopy(p, src, tgt):
            ratio = pageRatios[0 if p['size'].startswith("span") else 1]
            return self.carefulCopy(ratio, src, tgt, cropme)
        missingPics = []
        if info['document/ifinclfigs'] == 'false':
            # print("NoFigs")
            return []
        picinfos.build_searchlist()
        for j in jobs:
            picinfos.getFigureSources(keys=j, exclusive=self.printer.get("c_exclusiveFiguresFolder"))
            picinfos.set_destinations(fn=carefulCopy, keys=j, cropme=cropme)
        missingPics = [v['src'] for v in picinfos.values() if v['anchor'][:3] in jobs and 'dest file' not in v and 'src' in v]
        res = [os.path.join("tmpPics", v['dest file']) for v in picinfos.values() if 'dest file' in v]
        outfname = info.printer.baseTeXPDFnames(jobs)[0] + ".piclist"
        for k, v in list(picinfos.items()):
            m = v.get('media', '')
            if m and 'p' not in m:
                del picinfos[k]
        picinfos.out(os.path.join(self.tmpdir, outfname), bks=jobs, skipkey="disabled", usedest=True, media='p')
        res.append(outfname)
        info["document/piclistfile"] = outfname

        if len(missingPics):
            print(missingPics)
            missingPicList = ["{}".format(", ".join(list(set(missingPics))))]
            self.printer.set("l_missingPictureCount", "({} Missing)".format(len(set(missingPics))))
            self.printer.set("l_missingPictureString", "Missing Pictures: {}".format("\n".join(missingPicList)))
        else:
            self.printer.set("l_missingPictureCount", "(0 Missing)")
            self.printer.set("l_missingPictureString", "")
        return res

    def getBorder(self, box, start, end, fn):
        if start > end:
            it = range(box[start]-1, box[end]-1, -1)
        else:
            it = range(box[start], box[end])
        otheri = 0 if (start & 1) else 1
        others = box[otheri]
        othere = box[otheri+2]
        for t in it:
            score = sum(fn(t, i) for i in range(others, othere))
            # 8 = 256 * 5% (approx)
            if score > 8 * (othere - others):
                break
        return t

    def cropBorder(self, im):
        bwim = im.convert("L").load()
        box = im.getbbox()
        cbox = []
        cbox.append(self.getBorder(box, 0, 2, lambda x, y: bwim[x, y]))
        cbox.append(self.getBorder(box, 1, 3, lambda y, x: bwim[x, y]))     # top is 0
        cbox.append(self.getBorder(box, 2, 0, lambda x, y: bwim[x, y]))
        cbox.append(self.getBorder(box, 3, 1, lambda y, x: bwim[x, y]))
        cbox = tuple(cbox)
        if cbox != box:
            return im.crop(cbox)
        return im

    def convertToJPGandResize(self, ratio, infile, outfile, cropme):
        if self.ispdfxa:
            white = (0, 0, 0, 0)
            fmt = fmta = "CMYK"
        else:
            white = (255, 255, 255, 255)
            fmta = "RGBA"
            fmt = "RGB"
        with open(infile,"rb") as inf:
            rawdata = inf.read()
        newinf = cStringIO(rawdata)
        im = Image.open(newinf)
        if cropme:
            im = self.cropBorder(im)
        p = im.load()
        onlyRGBAimage = im.convert(fmta)
        iw = im.size[0]
        ih = im.size[1]
        if iw/ih < ratio:
            newWidth = int(ih * ratio)
            newimg = Image.new(fmta, (newWidth, ih), color=white)
            newimg.alpha_composite(onlyRGBAimage, (int((newWidth-iw)/2),0))
            iw = newimg.size[0]
            ih = newimg.size[1]
            onlyRGBimage = newimg.convert(fmt)
            onlyRGBimage.save(outfile)
        else:
            onlyRGBimage = onlyRGBAimage.convert(fmt)
            onlyRGBimage.save(outfile)
        return True

    def carefulCopy(self, ratio, srcpath, tgtfile, cropme):
        tmpPicPath = os.path.join(self.printer.working_dir, "tmpPics")
        tgtpath = os.path.join(tmpPicPath, tgtfile)
        try:
            im = Image.open(srcpath)
            iw = im.size[0]
            ih = im.size[1]
        except OSError:
            print(("Failed to get size of (image) file:"), srcpath)
        # If either the source image is a TIF (or) the proportions aren't right for page dimensions 
        # then we first need to convert to a JPG and/or pad with which space on either side
        if cropme or self.ispdfxa or iw/ih < ratio or os.path.splitext(srcpath)[1].lower().startswith(".tif"): # (.tif or .tiff)
            tgtpath = os.path.splitext(tgtpath)[0]+".jpg"
            try:
                self.convertToJPGandResize(ratio, srcpath, tgtpath, cropme)
            except: # MH: Which exception should I try to catch?
                print(_("Error: Unable to convert/resize image!\nImage skipped:"), srcpath)
                return os.path.basename(tgtpath)
        else:
            try:
                copyfile(srcpath, tgtpath)
            except OSError:
                print(_("Error: Unable to copy {}\n       image to {} in tmpPics folder"), srcpath, tgtpath)
                return os.path.basename(tgtpath)
        return os.path.basename(tgtpath)

    def removeTempFiles(self, texfiles):
        notDeleted = []
        # MH: Should we try to remove the generated Nested files (now that they are stored along with the config)?
        # What impact does that have on Paratext's S/R (cluttering)
        # n = os.path.join(self.tmpdir, "NestedStyles.sty")
        # if os.path.exists(n):
            # try:
                # os.remove(n)
            # except:
                # notDeleted += [n]
        for extn in ('delayed','parlocs', 'notepages', 'SFM', 'sfm', 'xdv', 'tex', 'log'):
            for t in set(texfiles):
                delfname = os.path.join(self.tmpdir, t.replace(".tex", "."+extn))
                if os.path.exists(delfname):
                    try:
                        os.remove(delfname)
                    except OSError:
                        notDeleted += [delfname]
        for f in self.books:
            delfname = os.path.join(self.tmpdir, f)
            if os.path.exists(delfname):
                try:
                    os.remove(delfname)
                except OSError:
                    notDeleted += [delfname]
        #folderList = ["tmpPics", "tmpPicLists"] 
        #notDeleted += self.removeTmpFolders(self.tmpdir, folderList)
        if len(notDeleted):
            self.printer.doError(_("Warning: Could not delete\ntemporary file(s) or folder(s):"),
                    secondary="\n".join(set(notDeleted)))

    def removeTmpFolders(self, base, delFolders, mkdirs=False):
        notDeleted = []
        for p in delFolders:
            path2del = os.path.join(base, p)
            if os.path.exists(path2del):
                try:
                    rmtree(path2del)
                except OSError:
                    notDeleted += [path2del]
            if mkdirs:
                os.makedirs(path2del)
        return notDeleted

    def usablePageRatios(self, info):
        pageHeight = self.convert2mm(info.dict["paper/height"])
        pageWidth = self.convert2mm(info.dict["paper/width"])
        # print("pageHeight =", pageHeight, "  pageWidth =", pageWidth)
        margin = self.convert2mm(info.dict["paper/margins"])
        # print("margin =", margin)
        sideMarginFactor = 1.0
        middleGutter = float(info.dict["document/colgutterfactor"])/3
        bindingGutter = float(info.dict["paper/gutter"]) if info.asBool("paper/ifaddgutter") else 0
        topMarginFactor = info.dict["paper/topmarginfactor"]
        bottomMarginFactor = info.dict["paper/bottommarginfactor"]
        lineSpacingFactor = float(info.dict["paragraph/linespacingfactor"])
        # print("lineSpacingFactor=", lineSpacingFactor)
        # ph = pageheight, pw = pagewidth
        # print("margin={} topMarginFactor={} bottomMarginFactor={}".format(margin, topMarginFactor, bottomMarginFactor))
        ph = pageHeight - (margin * float(topMarginFactor)) - (margin * float(bottomMarginFactor)) - 22
        pw1 = pageWidth - bindingGutter - (2*(margin*sideMarginFactor))                       # single-col layout
        if info.dict["paper/columns"] == "2":
            pw2 = int(pageWidth - middleGutter - bindingGutter - (2*(margin*sideMarginFactor)))/2 # double-col layout & span images
        else:
            pw2 = pw1
        # print("Usable ph: {}mm".format(ph), "     Usable 1-col pw1: {}mm   Usable 2-col pw2: {}mm".format(pw2, pw1))
        pageRatios = (pw1/ph, pw2/ph)
        # print("Page Ratios = ", pageRatios)
        return pageRatios

    def convert2mm(self, measure):
        _unitConv = {'mm':1, 'cm':10, 'in':25.4, '"':25.4}
        units = _unitConv.keys()
        num = float(re.sub(r"([0-9\.]+).*", r"\1", str(measure)))
        unit = str(measure)[len(str(num)):].strip(" ")
        return (num * _unitConv[unit]) if unit in units else num
