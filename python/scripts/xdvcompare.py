# -*- coding: utf-8 -*-
"""
Created on Mon Aug 10 10:50:42 2020

@author: jakem
"""

import argparse, os
from struct import unpack

opcodes = [("nop", [], i) for i in range(128)]
opcodes += [
    ("nop", [1], "setcode"),
    ("nop", [2], "setcode"),
    ("nop", [3], "setcode"),
    ("nop", [-4], "setcode"),
    ("nop", [-4]*2, "setrule"),
    ("nop", [1], "setcode"),
    ("nop", [2], "setcode"),
    ("nop", [3], "setcode"),
    ("nop", [-4], "setcode"),
    ("nop", [-4]*2, "setrule"),
    ("nop", [], "nop"),
    ("bop", [4]*10 + [-4], "bop"),
    ("simple", [], "eop"),       # code 140
    ("simple", [], "push"),
    ("simple", [], "pop"),
    ("move", [-1], "right"),
    ("move", [-2], "right"),
    ("move", [-3], "right"),
    ("move", [-4], "right"),
    ("move", [], "w"),
    ("move", [-1], "w"),
    ("move", [-2], "w"),
    ("move", [-3], "w"),         # code 150
    ("move", [-4], "w"),
    ("move", [], "x"),
    ("move", [-1], "x"),
    ("move", [-2], "x"),
    ("move", [-3], "x"),
    ("move", [-4], "x"),
    ("move", [-1], "down"),
    ("move", [-2], "down"),
    ("move", [-3], "down"),
    ("move", [-4], "down"),
    ("move", [], "y"),
    ("move", [-1], "y"),
    ("move", [-2], "y"),
    ("move", [-3], "y"),
    ("move", [-4], "y"),
    ("move", [], "z"),
    ("move", [-1], "z"),
    ("move", [-2], "z"),
    ("move", [-3], "z"),
    ("move", [-4], "z")]         # code 170
opcodes += [("font", [], i) for i in range(64)]
opcodes += [
    ("font", [1], None),
    ("font", [2], None),
    ("font", [3], None),
    ("font", [4], None),
    ("xxx", [1], "special"),
    ("xxx", [2], "special"),
    ("xxx", [3], "special"),
    ("xxx", [4], "special"),
    ("fontdef", [1, 4, 4, 4, 1, 1], None),
    ("fontdef", [2, 4, 4, 4, 1, 1], None),
    ("fontdef", [3, 4, 4, 4, 1, 1], None),
    ("fontdef", [4, 4, 4, 4, 1, 1], None),
    ("pre", [1, 4, 4, 4, 1], "pre"),
    ("post", [-4] + [4]*5 + [2,2], "post"),
    ("postpost", [4, 1], "postpost"),
    ("unknown", [], None),   # code 250
    ("xpic", [1, 4, 4, 4, 4, 4, 4, 2, 2], None),
    ("xfontdef", [4, 4, 2], "xfontdef"),
    ("xglyphs", [], "xglyphs 1"),
    ("xglyphs", [], "xglyphs 0"),
    ("parmop", [1], "direction")]

packings = ("bhxi", "BHxI")

class XDviReader:
    def __init__(self, filename, commonfonts, pagecounter, name=None, verbosity=0):
        self.filename = filename
        self.file = open(filename, "rb")
        self.filesize = os.path.getsize(filename)
        self.commonfonts = commonfonts # fontparam: common ID
        self.pageno = pagecounter
        self.name = name
        self.v = verbosity
        self.postvals = {}
        self.postread = False
        self.prevals = {}
        self.preread = False
        self.stack = []
        self.pos = [0, 0, 0, 0, 0, 0] # (h,v,w,x,y,z)
        self.pages = []
        self.fonts = {} # k: common ID
        self.readpost() # postvals ("p", "num", "den", "mag", "l", "u", "s", "t"): p = final bop, t = number of bops
        self.readpre() # prevals ("i", "num", "den", "mag", "comment"): i = version
        self.buildpagelist()
    
    def introduce(self):
        print("XDviReader {}: file size {:,}B; {} pages; {} fonts".format(self.name, self.filesize, self.postvals["t"], len(self.fonts)))
    
    def readbytes(self, num):
        return self.file.read(num)
       
    def readval(self, size, uint=False):
        d = self.readbytes(size)
        if size == 3:
            if uint:
                s = unpack(">"+packings[1][1]+packings[1][0], d)
                res = s[0] * 256 + s[1]
            else:
                s = unpack(">"+packings[0][1]+packings[1][0], d)
                res = s[0] * 256 + (s[1] if s[0] > 0 else -s[1])
        else:
            res = unpack(">"+packings[1 if uint else 0][size-1], d)[0]
        return res
    
    def readvalueloc(self, size, byteloc, uint=False):
        self.setpos(byteloc)
        return self.readval(size, uint)
    
    def setpos(self, location):
        assert 0 <= location <= self.filesize
        self.file.seek(location)
    
    def loadop(self):
        op = self.readval(1, True)
        opc = opcodes[op]
        data = [self.readval((x if x>0 else -x), uint=x>0) for x in opc[1]]
        lastparm = opc[2]
        if self.v > 3:
            print(op, lastparm, data, opc[0])
        return opc[0], op, lastparm, data
    
    def postposition(self):
        location = self.filesize
        val = 223
        while val == 223:
            location -= 1
            val = self.readvalueloc(1, location, True)
        if location == self.filesize - 1:
            print("File does not end with 223 signature; wrong type of file or file not intact")
            raise Exception
        self.setpos(location-5)
    
    def readpost(self):
        self.postposition()
        while True:
            command, op, lastparm, data = self.loadop()
            if lastparm == "postpost" and self.postread:
                break
            getattr(self, command)(op, lastparm, data)
    
    def readpre(self):
        self.setpos(0)
        command, op, lastparm, data = self.loadop()
        assert op == 247
        (i, n, d, m, k) = data        
        self.prevals.update(zip(("i", "num", "den", "mag", "comment"), [i, n, d, m, self.readbytes(k).decode("utf-8")]))
        self.preread = True
        
    def buildpagelist(self):
        assert self.postread
        loc = self.file.tell()
        p = self.postvals["p"]
        bops = []
        while p != -1:
            self.setpos(p)
            command, op, lastparm, data = self.loadop()
            assert op == 139
            bops.append(p)
            p = data[-1]
        assert len(bops) == self.postvals["t"]
        self.bops = list(reversed(bops))
        self.file.seek(loc)
    
    def setpagepos(self, pageindex): # Zero indexed
        assert 0 <= pageindex <= len(self.bops)
        self.setpos(self.bops[pageindex])

    def readpage(self):
        lastparm = None        
        while lastparm != "eop":
            command, op, lastparm, data = self.loadop()
            getattr(self, command)(op, lastparm, data)

    def nop(self, *a):
        pass

    def bop(self, *a):
        self.page = Page(self.pageno[0])
        self.stack = []
        self.pos = [0, 0, 0, 0, 0, 0]
    
    def simple(self, opcode, parm, data):
        getattr(self, parm)()
    
    def eop(self):
        self.pages.append(self.page)
        
    def push(self):
        self.stack.append(self.pos.copy())
    
    def pop(self):
        self.pos = self.stack.pop(-1)

    def move(self, opcode, parm, data):
        getattr(self, parm)(data[0] if data != [] else None)
        
    def right(self, dist):
        self.pos[0] += dist
    
    def down(self, dist):
        self.pos[1] += dist
        
    def w(self, dist=None):
        if dist is not None:
            self.pos[2] = dist
        self.right(self.pos[2])
        
    def x(self, dist=None):
        if dist is not None:
            self.pos[3] = dist
        self.right(self.pos[3])

    def y(self, dist=None):
        if dist is not None:
            self.pos[4] = dist
        self.down(self.pos[4])
        
    def z(self, dist=None):
        if dist is not None:
            self.pos[5] = dist
        self.down(self.pos[5])
        
    
    def font(self, op, parm, data):
        if parm is not None:
            data = [parm]
        self.activefont = self.fonts[data[0]]
    
    def xxx(self, opcode, parm, data):
        txt = self.readbytes(data[0])
        self.page.specials.append(txt)
        if self.v > 2:
            print(txt)
        
    def post(self, opcode, parmname, data):
        self.postvals.update(zip(("p", "num", "den", "mag", "l", "u", "s", "t"), data))
        self.postread = True
        
    def postpost(self, opcode, parmname, data):
        self.postvals["i"] = data[1]
        self.postvals["q"] = data[0]
        self.setpos(self.postvals["q"])
    
    def xfontdef(self, opcode, parm, data):
        (k, points, flags) = data
        plen = self.readval(1, uint=True)
        font_name = os.path.basename(self.readbytes(plen).decode("utf-8"))
        color = self.readval(4) if flags & 0x200 else 0xFFFFFFFF
        if flags & 0x800:       # variations
            nvars = self.readval(2)
            variations = [self.readval(4) for i in range(nvars)]
        else:
            variations = []
        ext = self.readval(4) if flags & 0x1000 else 0
        slant = self.readval(4) if flags & 0x2000 else 0
        embolden = self.readval(4) if flags & 0x4000 else 0
        ident = self.readval(4)
        #flags = 0x1234
        fontparam = (font_name, points, "{:08X}".format(color), "{:04X}".format(flags), *variations, ext, slant, embolden)
        if fontparam not in self.commonfonts:
            fontid = len(self.commonfonts)
            self.commonfonts[fontparam] = fontid
        if k not in self.fonts:
            self.fonts[k] = self.commonfonts[fontparam]
        
    def xglyphs(self, opcode, parm, data):
        width = self.readval(4)
        slen = self.readval(2, uint=True)
        if parm:
            pos = [(self.readval(4), self.readval(4)) for i in range(slen)]
        else:
            pos = [(self.readval(4), 0) for i in range(slen)]
        glyphs = [self.readval(2) for i in range(slen)]
        
        dig = 0
        self.page.glyphs += [
            (glyphs[i], 
             round(pos[i][0]+self.pos[1],dig), 
             round(pos[i][1]+self.pos[0],dig), 
             self.activefont) for i in range(slen)
            ] ########## This needs checking; does xglyphs move the cursor at all?
    
    def pointstomm(self, dist):
        return (dist * self.prevals["num"] * self.prevals["mag"]) / (self.prevals["den"] * 10**7)
    
    def mmtopoints(self, mm):
       return (mm * self.prevals["den"] * 10**7) /(self.prevals["num"] * self.prevals["mag"]) 

class Page:
    def __init__(self, pageno=None):
        self.pageno = pageno
        self.glyphs = []
        self.specials = []
    
    def __repr__(self):
        return "Page {} with {} glyphs and {} specials".format(self.pageno, len(self.glyphs), len(self.specials))
    
    def __eq__(self, otherpage):
        if len(self.glyphs) != len(otherpage.glyphs):
            return False
        if self.glyphs == otherpage.glyphs:
            return True
        self.sortglyphs()
        otherpage.sortglyphs()
        if self.glyphs == otherpage.glyphs:
            return True
        for i in range(len(self.glyphs)):
            glyph1 = self.glyphs.pop(0)
            glyph2 = otherpage.glyphs.pop(0)
            if glyph1 == glyph2:
                continue
            elif glyphnear(glyph1, glyph2):
                print("Nearby")
                continue
            else:
                return False
        else:
            return True ###### Not 100% sure this is correct
    
    def sortglyphs(self):
        self.glyphs.sort(key=lambda x:(x[1], x[2]))
    
    def getdiff(self, otherpage):
        self.sortglyphs()
        otherpage.sortglyphs()
        if self.glyphs == otherpage.glyphs:
            return 0
        for i in reversed(range(len(self.glyphs))):
            if self.glyphs[i] in otherpage.glyphs:
                otherpage.glyphs.remove(self.glyphs.pop(i))
        if self.glyphs == otherpage.glyphs:
            return 0
        for i in reversed(range(len(self.glyphs))):
            for j in reversed(range(len(otherpage.glyphs))):
                if glyphnear(self.glyphs[i], otherpage.glyphs[j]):
                    self.glyphs.pop(i)
                    otherpage.glyphs.pop(j)
                    break
        return max(len(self.glyphs), len(otherpage.glyphs))

def glyphnear(glyph1, glyph2, allowfontmismatch=False):
    if glyph1[0] != glyph2[0]:
        return False
    if not allowfontmismatch and glyph1[3] != glyph2[3]:
        return False
    return (glyph1[1] - glyph2[1])**2 + (glyph1[2] - glyph2[2])**2 < sqthresh

class Comparator:
    def __init__(self, filename1, filename2, prediction=True, pmm=False, v=0):
        self.fontdict = {}
        self.pageno = [1] # A list because it's mutable/readable by the XDviReader objects; the update is carried through automatically
        self.v = v
        if "project" in filename1 and "standard" in filename2:
            name1, name2 = "Project", "Standard"
        elif "project" in filename2 and "standard" in filename1:
            name2, name1 = "Project", "Standard"
        else:
            name1, name2 = "Xdv 1", "Xdv 2"
        self.readers = [XDviReader(filename1, self.fontdict, self.pageno, name=name1, verbosity=v),
                        XDviReader(filename2, self.fontdict, self.pageno, name=name2, verbosity=v)]
        self.mmtolerance = 2.5
        self.allowpagemismatch = pmm
        self.pred = prediction and not pmm
        if self.v > 0:
            self.introduce()
            [ reader.introduce() for reader in self.readers]
    
    def introduce(self):
        print("Comparator: glyph positioning tolerance {}mm; Page mismatching is {}allowed; Smart failure prediction: {}".format(self.mmtolerance, "" if self.allowpagemismatch else "not ", "on" if self.pred else "off"))
    
    def predictfailure(self):
        locs = [ reader.bops + [reader.postvals["q"]] for reader in self.readers ]
        assert len(locs[0]) == len(locs[1])
        lens = [(locs[0][i+1]-locs[0][i]) / (locs[1][i+1]-locs[1][i]) for i in range(len(self.readers[0].bops)) ]
        av = sum(lens)/len(lens)
        lens = [val/av for val in lens]
        for i in range(len(lens)):
            if i != 0 and (lens[i] < 0.9997 or lens[i] > 1.0003):
                return i
        else:
            return 0
    
    def getorder(self):
        def startat(order, n):
            if type(order) is not list:
                order = list(order)
            return order[n:]+order[:n]
        seq = startat(range(self.numpages), self.predictfailure()) if self.pred else range(self.numpages)
        if self.v > 0:
            print("Starting at page {}".format(seq[0] + 1))
        return seq
        
    def compare(self):
        errors = ""
        failedat = None
        #if True:#
        try:
            try:
                assert self.readers[0].postvals["t"] == self.readers[1].postvals["t"]
                self.numpages = self.readers[0].postvals["t"]
            except:
                errors += "\nMatch failed because input files have different lengths: {} pages vs {} pages".format(self.readers[0].postvals["t"], self.readers[1].postvals["t"])
                failedat = "postamble"
                if not self.allowpagemismatch:
                    raise Exception
                else:
                    self.numpages = self.readers[0].postvals["t"]
            global sqthresh 
            sqthresh = (self.readers[0].mmtopoints(self.mmtolerance))**2
            for i in self.getorder():
                self.pageno[0] = i+1
                for reader in self.readers:
                    reader.setpagepos(i)
                    reader.readpage()
                    if self.v > 1:
                        print(reader.page)
                try:
                    assert self.readers[0].page == self.readers[1].page
                except:
                    errors += "\nGlyphs did not line up closely enough"
                    failedat = None
                    if self.v > 0:
                        errors += "\n{} unmatchable glyphs were found on page {}".format(self.readers[0].page.getdiff(self.readers[1].page), self.pageno[0])
                    raise Exception
            print("Test executed successfully")
            failedat = "Didn't fail"
        #if True:#
        except:
            if failedat is None:
                failedat = "page {}".format(self.pageno[0])
            print("Failure occurred at {}".format(failedat))
            print(errors)

parser = argparse.ArgumentParser()
parser.add_argument("infile1", help="Input xdvi file1")
parser.add_argument("infile2", help="Input xdvi file2")
parser.add_argument("-v","--verbose", action="count", default=0, help="Verbosity: v = basic info, vv = page summary, vvv = specials, vvvv = every operation")
parser.add_argument("-s", "--superficial", action="store_true", help="Load files but do not compare; check for file intactness")
parser.add_argument("-n", "--notclever", action="store_true", help="Don't predict failure location")
parser.add_argument("-p", "--pagemismatch", action="store_true", help="Allow comparison of documents of mismatched length")
args = parser.parse_args()

comp = Comparator(args.infile1, args.infile2, prediction=not args.notclever, pmm=args.pagemismatch, v=int(args.verbose))
if not args.superficial:
    comp.compare()
