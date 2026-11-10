#!/usr/bin/env python3
"""Filer – eigene Mac-App ohne Compiler (PyObjC).

Randloses Fenster, rastet an Bildschirmrändern und Ecken ein,
wahlweise immer vorne, normal oder hinten auf dem Schreibtisch.
"""
import json
from pathlib import Path

import objc
from Foundation import NSObject, NSURL, NSMakeRect, NSBundle, NSNull
from AppKit import (NSApplication, NSWindow, NSView, NSColor, NSScreen, NSEvent, NSCursor,
                    NSMenu, NSMenuItem, NSImage, NSBezierPath, NSTrackingArea)
import AppKit
import WebKit
import Quartz
from PyObjCTools import AppHelper

DATA = Path.home() / ".filer.json"
GHFILE = Path.home() / ".filer-gh.json"
CACHE = Path.home() / ".filer" / "index.html"   # automatisch geladene neue Version
REMOTE = "https://raw.githubusercontent.com/benvoemel-a11y/Stockwise/main/filer/mac/index.html"


def page_version(text):
    import re
    m = re.search(r"Filer Mac v(\d+)", text or "")
    return int(m.group(1)) if m else 0


def best_page():
    """Neueste Oberfläche: mitgeliefert oder automatisch geladen."""
    own = RES / "index.html"
    try:
        if CACHE.exists() and page_version(CACHE.read_text("utf-8")) > page_version(own.read_text("utf-8")):
            return CACHE
    except Exception:
        pass
    return own   # GitHub-Schlüssel, bleibt nur auf diesem Mac
RES = Path(__file__).resolve().parent
TOP, EDGE, CORNER, MAGNET, RADIUS = 20, 5, 14, 18, 0
GREY = NSColor.colorWithSRGBRed_green_blue_alpha_(0x8a / 255, 0x8a / 255, 0x8a / 255, 1.0)
DESKTOP_LEVEL = Quartz.CGWindowLevelForKey(Quartz.kCGDesktopIconWindowLevelKey) + 1

BORDERLESS, MINIATURIZABLE, RESIZABLE = 0, 1 << 2, 1 << 3
BUFFERED = 2


def screen_at(x, y):
    for s in NSScreen.screens():
        f = s.frame()
        if f.origin.x <= x < f.origin.x + f.size.width and f.origin.y <= y < f.origin.y + f.size.height:
            return s
    return NSScreen.mainScreen()


def fit(x, y, w, h, vf, m=MAGNET):
    """Hält das Fenster auf dem Bildschirm und zieht es nah am Rand bündig an die Wand."""
    vx, vy, vw, vh = vf.origin.x, vf.origin.y, vf.size.width, vf.size.height
    w, h = min(w, vw), min(h, vh)
    x = max(vx, min(x, vx + vw - w))
    y = max(vy, min(y, vy + vh - h))
    if x - vx < m:
        x = vx
    elif vx + vw - (x + w) < m:
        x = vx + vw - w
    if y - vy < m:
        y = vy
    elif vy + vh - (y + h) < m:
        y = vy + vh - h
    return NSMakeRect(x, y, w, h)


def http_request(method, url, headers, body):
    """Holt/schreibt über das Internet (GitHub-Sync). Gibt (status, text) zurück."""
    import ssl
    import urllib.request
    import urllib.error
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    data = body.encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    req.add_header("User-Agent", "Filer-Mac")
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            txt = e.read().decode("utf-8", "replace")
        except Exception:
            txt = ""
        return e.code, txt
    except Exception as exc:
        print("Filer http:", exc)
        return 0, ""


def send_notification(title, text):
    """macOS-Mitteilung ohne Server: über das eingebaute AppleScript."""
    import subprocess

    def q(t):
        return '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'
    script = "display notification %s with title %s" % (q(text), q(title))
    try:
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        print("Filer notify:", exc)


class FilerWindow(NSWindow):
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True


class DragView(NSView):
    """Ziehleiste oben: verschiebt das Fenster und lässt es an Wänden und Ecken einrasten."""

    def acceptsFirstMouse_(self, event):
        return True

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), NSCursor.openHandCursor())

    def mouseDown_(self, event):
        m = NSEvent.mouseLocation()
        o = self.window().frame().origin
        self.start = (m.x, m.y, o.x, o.y)
        NSCursor.closedHandCursor().set()

    def mouseDragged_(self, event):
        win = self.window()
        m = NSEvent.mouseLocation()
        mx, my, ox, oy = self.start
        f = win.frame()
        vf = screen_at(m.x, m.y).visibleFrame()
        win.setFrame_display_(fit(ox + m.x - mx, oy + m.y - my, f.size.width, f.size.height, vf), True)

    def mouseUp_(self, event):
        NSCursor.openHandCursor().set()
        self.window().saveFrameUsingName_("FilerWindow")


class ResizeView(NSView):
    """Unsichtbare Griffe an Rändern und Ecken zum Größe ändern."""

    def acceptsFirstMouse_(self, event):
        return True

    def resetCursorRects(self):
        side = getattr(self, "side", set())
        if side == {"bottom"}:
            cursor = NSCursor.resizeUpDownCursor()
        elif len(side) == 1:
            cursor = NSCursor.resizeLeftRightCursor()
        else:
            cursor = NSCursor.crosshairCursor()
        self.addCursorRect_cursor_(self.bounds(), cursor)

    def mouseDown_(self, event):
        m = NSEvent.mouseLocation()
        f = self.window().frame()
        self.start = (m.x, m.y, f.origin.x, f.origin.y, f.size.width, f.size.height)

    def mouseDragged_(self, event):
        win = self.window()
        m = NSEvent.mouseLocation()
        mx, my, x, y, w, h = self.start
        dx, dy = m.x - mx, m.y - my
        mw, mh = win.minSize().width, win.minSize().height
        vf = screen_at(x + w / 2, y + h / 2).visibleFrame()
        vx, vy, vw = vf.origin.x, vf.origin.y, vf.size.width
        nx, ny, nw, nh = x, y, w, h
        if "right" in self.side:
            nw = max(mw, min(w + dx, vx + vw - x))
        if "left" in self.side:
            nx = max(vx, min(x + dx, x + w - mw))
            nw = x + w - nx
        if "bottom" in self.side:
            ny = max(vy, min(y + dy, y + h - mh))
            nh = y + h - ny
        win.setFrame_display_(NSMakeRect(nx, ny, nw, nh), True)

    def mouseUp_(self, event):
        self.window().saveFrameUsingName_("FilerWindow")


DOT_COLORS = {
    "rot": "d93f37", "schwarz": "1f1f1f", "weiss": "ffffff", "pink": "ff4f9a",
    "blau": "2f7cf6", "orange": "f47b2a", "gelb": "ffcc00", "gruen": "34c759",
}
DOT = {"name": "rot"}


def hex_color(h, f=1.0, a=1.0):
    r, g, b = (int(h[i:i + 2], 16) / 255 * f for i in (0, 2, 4))
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a)


class CloseButton(NSView):
    """Roter Mac-Knopf oben links: zeigt beim Drüberfahren ein x und beendet Filer."""

    def initWithFrame_(self, frame):
        self = objc.super(CloseButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.hover = False
        area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            AppKit.NSTrackingMouseEnteredAndExited | AppKit.NSTrackingActiveAlways | AppKit.NSTrackingInVisibleRect,
            self, None)
        self.addTrackingArea_(area)
        return self

    def acceptsFirstMouse_(self, event):
        return True

    def mouseEntered_(self, event):
        self.hover = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self.hover = False
        self.setNeedsDisplay_(True)

    def mouseDown_(self, event):
        pass

    def mouseUp_(self, event):
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        b = self.bounds()
        if 0 <= p.x <= b.size.width and 0 <= p.y <= b.size.height:
            NSApplication.sharedApplication().terminate_(None)

    def drawRect_(self, rect):
        b = self.bounds()
        d = 12.0
        x, y = (b.size.width - d) / 2, (b.size.height - d) / 2
        name = DOT["name"] if DOT["name"] in DOT_COLORS else "rot"
        hx = DOT_COLORS[name]
        hex_color(hx).setFill()
        circle = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, y, d, d))
        circle.fill()
        (hex_color("9a9a9a") if name == "weiss" else hex_color(hx, 0.82)).setStroke()
        circle.setLineWidth_(0.5)
        circle.stroke()
        if getattr(self, "hover", False):
            cx, cy, r = x + d / 2, y + d / 2, 2.6
            path = NSBezierPath.bezierPath()
            path.setLineWidth_(1.3)
            path.setLineCapStyle_(AppKit.NSRoundLineCapStyle)
            path.moveToPoint_((cx - r, cy - r))
            path.lineToPoint_((cx + r, cy + r))
            path.moveToPoint_((cx - r, cy + r))
            path.lineToPoint_((cx + r, cy - r))
            if name in ("weiss", "gelb"):
                hex_color("3a3a3a", 1.0, 0.75).setStroke()
            elif name == "schwarz":
                hex_color("b9b9b9", 1.0, 0.9).setStroke()
            else:
                hex_color(hx, 0.35, 0.85).setStroke()
            path.stroke()


class AppDelegate(NSObject, protocols=[objc.protocolNamed("WKScriptMessageHandler")]):

    def applicationDidFinishLaunching_(self, notification):
        self.buildMenu()
        icon = NSImage.alloc().initWithContentsOfFile_(str(RES / "icon.png"))
        if icon:
            NSApplication.sharedApplication().setApplicationIconImage_(icon)

        text, level = "null", "normal"
        try:
            text = DATA.read_text("utf-8")
            obj = json.loads(text)
            level = obj.get("level", "normal")
            DOT["name"] = obj.get("dot", "rot")
        except Exception:
            text = "null"

        ghtext = "null"
        try:
            ghtext = json.dumps(json.loads(GHFILE.read_text("utf-8")))
        except Exception:
            ghtext = "null"

        content = WebKit.WKUserContentController.alloc().init()
        content.addScriptMessageHandler_name_(self, "filer")
        self.content = content
        self.injectData()
        config = WebKit.WKWebViewConfiguration.alloc().init()
        config.setUserContentController_(content)

        rect = NSMakeRect(0, 0, 380, 560)
        win = FilerWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, BORDERLESS | RESIZABLE | MINIATURIZABLE, BUFFERED, False)
        win.setTitle_("Filer")
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        win.setMinSize_((260, 260))
        win.setReleasedWhenClosed_(False)
        self.window = win

        root = NSView.alloc().initWithFrame_(rect)
        root.setWantsLayer_(True)
        root.layer().setBackgroundColor_(GREY.CGColor())
        root.layer().setCornerRadius_(RADIUS)
        root.layer().setMasksToBounds_(True)
        win.setContentView_(root)

        web = WebKit.WKWebView.alloc().initWithFrame_configuration_(root.bounds(), config)
        web.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        web.setValue_forKey_(False, "drawsBackground")
        root.addSubview_(web)
        self.web = web
        self.addHandles(root)

        if not win.setFrameUsingName_("FilerWindow"):
            win.center()
        f = win.frame()
        screen = win.screen() or NSScreen.mainScreen()
        win.setFrame_display_(fit(f.origin.x, f.origin.y, f.size.width, f.size.height,
                                  screen.visibleFrame(), 0), False)
        self.applyLevel(level)

        index = best_page()
        self.page = index
        web.loadFileURL_allowingReadAccessToURL_(NSURL.fileURLWithPath_(str(index)),
                                                 NSURL.fileURLWithPath_(str(index.parent)))
        self.checkUpdate()
        win.makeKeyAndOrderFront_(None)
        win.makeFirstResponder_(web)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    @objc.python_method
    def addHandles(self, root):
        b = root.bounds()
        w, h = b.size.width, b.size.height
        drag = DragView.alloc().initWithFrame_(NSMakeRect(0, h - TOP, w, TOP))
        drag.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
        root.addSubview_(drag)
        close = CloseButton.alloc().initWithFrame_(NSMakeRect(6, h - 22, 16, 16))
        close.setAutoresizingMask_(AppKit.NSViewMaxXMargin | AppKit.NSViewMinYMargin)
        root.addSubview_(close)
        self.close = close
        handles = [
            ({"right"}, (w - EDGE, 0, EDGE, h - TOP), AppKit.NSViewMinXMargin | AppKit.NSViewHeightSizable),
            ({"left"}, (0, 0, EDGE, h - TOP), AppKit.NSViewMaxXMargin | AppKit.NSViewHeightSizable),
            ({"bottom"}, (0, 0, w, EDGE), AppKit.NSViewWidthSizable | AppKit.NSViewMaxYMargin),
            ({"right", "bottom"}, (w - CORNER, 0, CORNER, CORNER), AppKit.NSViewMinXMargin | AppKit.NSViewMaxYMargin),
            ({"left", "bottom"}, (0, 0, CORNER, CORNER), AppKit.NSViewMaxXMargin | AppKit.NSViewMaxYMargin),
        ]
        for side, r, mask in handles:
            v = ResizeView.alloc().initWithFrame_(NSMakeRect(*r))
            v.side = side
            v.setAutoresizingMask_(mask)
            root.addSubview_(v)

    @objc.python_method
    def applyLevel(self, level):
        win = self.window
        if level == "front":
            win.setLevel_(AppKit.NSFloatingWindowLevel)
            win.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                       | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        elif level == "back":
            win.setLevel_(DESKTOP_LEVEL)
            win.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                       | AppKit.NSWindowCollectionBehaviorStationary
                                       | AppKit.NSWindowCollectionBehaviorIgnoresCycle)
        else:
            win.setLevel_(AppKit.NSNormalWindowLevel)
            win.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorManaged)

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        try:
            body = message.body()
            kind = body["type"]
            if kind == "save":
                tmp = DATA.with_suffix(".tmp")
                tmp.write_text(str(body["json"]), "utf-8")
                tmp.replace(DATA)
            elif kind == "notify":
                v = body["value"]
                send_notification(str(v["title"]), str(v["body"]))
            elif kind == "dot":
                DOT["name"] = str(body["value"])
                self.close.setNeedsDisplay_(True)
            elif kind == "level":
                self.applyLevel(str(body["value"]))
            elif kind == "reload":
                self.reloadPage()
            elif kind == "gh":
                v = body["value"]
                if v is None or isinstance(v, NSNull):
                    GHFILE.unlink(missing_ok=True)
                else:
                    GHFILE.write_text(json.dumps({"token": str(v["token"]), "login": str(v["login"])}), "utf-8")
                    GHFILE.chmod(0o600)
            elif kind == "http":
                v = body["value"]
                self.startHttp(int(v["id"]), str(v["method"]), str(v["url"]),
                               {str(k): str(x) for k, x in dict(v["headers"] or {}).items()},
                               str(v["body"]) if isinstance(v["body"], str) else None)
        except Exception as exc:  # nie abstürzen, nur protokollieren
            print("Filer:", exc)

    @objc.python_method
    def injectData(self):
        text, ghtext = "null", "null"
        try:
            text = json.dumps(json.loads(DATA.read_text("utf-8")))
        except Exception:
            text = "null"
        try:
            ghtext = json.dumps(json.loads(GHFILE.read_text("utf-8")))
        except Exception:
            ghtext = "null"
        self.content.removeAllUserScripts()
        script = WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            "window.FILER_DATA = %s; window.FILER_GH = %s;" % (text, ghtext),
            WebKit.WKUserScriptInjectionTimeAtDocumentStart, True)
        self.content.addUserScript_(script)

    @objc.python_method
    def checkUpdate(self):
        """Holt im Hintergrund die neueste Filer-Oberfläche von GitHub (wie beim iPhone)."""
        import threading
        import time

        def work():
            while True:
                try:
                    status, text = http_request("GET", REMOTE + "?t=%d" % int(time.time()), {}, None)
                    cur = page_version(self.page.read_text("utf-8"))
                    if status == 200 and "</html>" in text and page_version(text) > cur:
                        CACHE.parent.mkdir(parents=True, exist_ok=True)
                        tmp = CACHE.with_suffix(".tmp")
                        tmp.write_text(text, "utf-8")
                        tmp.replace(CACHE)
                        AppHelper.callAfter(self.askReload)
                except Exception as exc:
                    print("Filer update:", exc)
                time.sleep(600)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def askReload(self):
        js = "window.__updateReady && window.__updateReady()"
        self.web.evaluateJavaScript_completionHandler_(js, None)

    @objc.python_method
    def reloadPage(self):
        self.page = best_page()
        self.injectData()
        self.web.loadFileURL_allowingReadAccessToURL_(NSURL.fileURLWithPath_(str(self.page)),
                                                      NSURL.fileURLWithPath_(str(self.page.parent)))

    @objc.python_method
    def startHttp(self, rid, method, url, headers, body):
        import threading

        def work():
            status, text = http_request(method, url, headers, body)
            js = "window.__http && window.__http(%d, %d, %s)" % (rid, status, json.dumps(text))
            AppHelper.callAfter(self.web.evaluateJavaScript_completionHandler_, js, None)

        threading.Thread(target=work, daemon=True).start()

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return True

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, flag):
        self.window.makeKeyAndOrderFront_(None)
        return True

    @objc.python_method
    def buildMenu(self):
        def item(title, action, key):
            return NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)

        main = NSMenu.alloc().init()
        app_item = NSMenuItem.alloc().init()
        main.addItem_(app_item)
        app_menu = NSMenu.alloc().initWithTitle_("Filer")
        app_menu.addItem_(item("Filer ausblenden", "hide:", "h"))
        app_menu.addItem_(NSMenuItem.separatorItem())
        app_menu.addItem_(item("Filer beenden", "terminate:", "q"))
        app_menu.addItem_(item("Fenster schließen", "terminate:", "w"))
        app_item.setSubmenu_(app_menu)

        edit_item = NSMenuItem.alloc().init()
        main.addItem_(edit_item)
        edit = NSMenu.alloc().initWithTitle_("Bearbeiten")
        for title, action, key in [("Widerrufen", "undo:", "z"), ("Wiederholen", "redo:", "Z"),
                                   ("Ausschneiden", "cut:", "x"), ("Kopieren", "copy:", "c"),
                                   ("Einsetzen", "paste:", "v"), ("Alles auswählen", "selectAll:", "a")]:
            edit.addItem_(item(title, action, key))
        edit_item.setSubmenu_(edit)

        win_item = NSMenuItem.alloc().init()
        main.addItem_(win_item)
        win_menu = NSMenu.alloc().initWithTitle_("Fenster")
        win_menu.addItem_(item("Im Dock ablegen", "miniaturize:", "m"))
        win_item.setSubmenu_(win_menu)
        NSApplication.sharedApplication().setMainMenu_(main)


def main():
    # Name „Filer“ statt „Python“ in Menüleiste und Dock
    try:
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "Filer"
    except Exception:
        pass
    app = NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
