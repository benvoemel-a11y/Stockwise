#!/usr/bin/env python3
"""Filer – eigene Mac-App ohne Compiler (PyObjC).

Randloses Fenster, rastet an Bildschirmrändern und Ecken ein,
wahlweise immer vorne, normal oder hinten auf dem Schreibtisch.
"""
import json
from pathlib import Path

import objc
from Foundation import NSObject, NSURL, NSMakeRect, NSBundle
from AppKit import (NSApplication, NSWindow, NSView, NSColor, NSScreen, NSEvent, NSCursor,
                    NSMenu, NSMenuItem, NSImage, NSBezierPath, NSTrackingArea)
import AppKit
import WebKit
import Quartz
from PyObjCTools import AppHelper

DATA = Path.home() / ".filer.json"
RES = Path(__file__).resolve().parent
TOP, EDGE, CORNER, MAGNET, RADIUS = 20, 5, 14, 18, 0
GREY = NSColor.colorWithSRGBRed_green_blue_alpha_(0xb9 / 255, 0xb9 / 255, 0xb9 / 255, 1.0)
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
        NSColor.colorWithSRGBRed_green_blue_alpha_(0xd9 / 255, 0x3f / 255, 0x37 / 255, 1.0).setFill()
        circle = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, y, d, d))
        circle.fill()
        NSColor.colorWithSRGBRed_green_blue_alpha_(0xb8 / 255, 0x30 / 255, 0x2a / 255, 1.0).setStroke()
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
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.35, 0.0, 0.0, 0.8).setStroke()
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
            level = json.loads(text).get("level", "normal")
        except Exception:
            text = "null"

        content = WebKit.WKUserContentController.alloc().init()
        content.addScriptMessageHandler_name_(self, "filer")
        script = WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            "window.FILER_DATA = %s;" % text, WebKit.WKUserScriptInjectionTimeAtDocumentStart, True)
        content.addUserScript_(script)
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

        index = RES / "index.html"
        web.loadFileURL_allowingReadAccessToURL_(NSURL.fileURLWithPath_(str(index)),
                                                 NSURL.fileURLWithPath_(str(RES)))
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
            elif kind == "level":
                self.applyLevel(str(body["value"]))
        except Exception as exc:  # nie abstürzen, nur protokollieren
            print("Filer:", exc)

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
