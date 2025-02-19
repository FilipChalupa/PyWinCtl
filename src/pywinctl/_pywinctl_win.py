#!/usr/bin/python
# -*- coding: utf-8 -*-

import ctypes
from ctypes import wintypes
import sys
import re
import threading
import time
import traceback
from typing import List, Tuple

import win32api
import win32con
import win32gui
import win32gui_struct
import win32process
from win32com.client import GetObject

from pywinctl import pointInRect, BaseWindow, Rect, Point, Size, Re, _WinWatchDog

# WARNING: Changes are not immediately applied, specially for hide/show (unmap/map)
#          You may set wait to True in case you need to effectively know if/when change has been applied.
WAIT_ATTEMPTS = 10
WAIT_DELAY = 0.025  # Will be progressively increased on every retry


def checkPermissions(activate: bool = False):
    """
    macOS ONLY: Check Apple Script permissions for current script/app and, optionally, shows a
    warning dialog and opens security preferences

    :param activate: If ''True'' and if permissions are not granted, shows a dialog and opens security preferences.
                     Defaults to ''False''
    :return: returns ''True'' if permissions are already granted or platform is not macOS
    """
    return True


def getActiveWindow():
    """
    Get the currently active (focused) Window

    :return: Window object or None
    """
    hWnd = win32gui.GetForegroundWindow()
    if hWnd:
        return Win32Window(hWnd)
    else:
        return None


def getActiveWindowTitle() -> str:
    """
    Get the title of the currently active (focused) Window

    :return: window title as string or empty
    """
    hWnd = getActiveWindow()
    if hWnd:
        return hWnd.title
    else:
        return ""


def getAllWindows():
    """
    Get the list of Window objects for all visible windows

    :return: list of Window objects
    """
    return [
        Win32Window(hwnd) for hwnd
        in _findWindowHandles(onlyVisible=True)
        if win32gui.IsWindowVisible(hwnd)]


def getAllTitles() -> List[str]:
    """
    Get the list of titles of all visible windows

    :return: list of titles as strings
    """
    return [window.title for window in getAllWindows()]


def getWindowsWithTitle(title, app=(), condition=Re.IS, flags=0):
    """
    Get the list of window objects whose title match the given string with condition and flags.
    Use ''condition'' to delimit the search. Allowed values are stored in pywinctl.Re sub-class (e.g. pywinctl.Re.CONTAINS)
    Use ''flags'' to define additional values according to each condition type:

        - IS -- window title is equal to given title (allowed flags: Re.IGNORECASE)
        - CONTAINS -- window title contains given string (allowed flags: Re.IGNORECASE)
        - STARTSWITH -- window title starts by given string (allowed flags: Re.IGNORECASE)
        - ENDSWITH -- window title ends by given string (allowed flags: Re.IGNORECASE)
        - NOTIS -- window title is not equal to given title (allowed flags: Re.IGNORECASE)
        - NOTCONTAINS -- window title does NOT contains given string (allowed flags: Re.IGNORECASE)
        - NOTSTARTSWITH -- window title does NOT starts by given string (allowed flags: Re.IGNORECASE)
        - NOTENDSWITH -- window title does NOT ends by given string (allowed flags: Re.IGNORECASE)
        - MATCH -- window title matched by given regex pattern (allowed flags: regex flags, see https://docs.python.org/3/library/re.html)
        - NOTMATCH -- window title NOT matched by given regex pattern (allowed flags: regex flags, see https://docs.python.org/3/library/re.html)
        - EDITDISTANCE -- window title matched using Levenshtein edit distance to a given similarity percentage (allowed flags: 0-100. Defaults to 90)
        - DIFFRATIO -- window title matched using difflib similarity ratio (allowed flags: 0-100. Defaults to 90)

    :param title: title or regex pattern to match, as string
    :param app: (optional) tuple of app names. Defaults to ALL (empty list)
    :param condition: (optional) condition to apply when searching the window. Defaults to ''Re.IS'' (is equal to)
    :param flags: (optional) specific flags to apply to condition. Defaults to 0 (no flags)
    :return: list of Window objects
    """
    matches = []
    if title and condition in Re._cond_dic.keys():
        lower = False
        if condition in (Re.MATCH, Re.NOTMATCH):
            title = re.compile(title, flags)
        elif condition in (Re.EDITDISTANCE, Re.DIFFRATIO):
            # flags = Re.IGNORECASE | ratio -> lower = flags & Re.IGNORECASE == Re.IGNORECASE / ratio = flags ^ Re.IGNORECASE
            if not isinstance(flags, int) or not (0 < flags <= 100):
                flags = 90
        elif flags == Re.IGNORECASE:
            lower = True
            title = title.lower()
        for win in getAllWindows():
            if win.title and Re._cond_dic[condition](title, win.title.lower() if lower else win.title, flags) \
                    and (not app or (app and win.getAppName() in app)):
                matches.append(win)
    return matches


def getAllAppsNames() -> List[str]:
    """
    Get the list of names of all visible apps

    :return: list of names as strings
    """
    return list(getAllAppsWindowsTitles().keys())


def getAppsWithName(name, condition=Re.IS, flags=0):
    """
    Get the list of app names which match the given string using the given condition and flags.
    Use ''condition'' to delimit the search. Allowed values are stored in pywinctl.Re sub-class (e.g. pywinctl.Re.CONTAINS)
    Use ''flags'' to define additional values according to each condition type:

        - IS -- app name is equal to given title (allowed flags: Re.IGNORECASE)
        - CONTAINS -- app name contains given string (allowed flags: Re.IGNORECASE)
        - STARTSWITH -- app name starts by given string (allowed flags: Re.IGNORECASE)
        - ENDSWITH -- app name ends by given string (allowed flags: Re.IGNORECASE)
        - NOTIS -- app name is not equal to given title (allowed flags: Re.IGNORECASE)
        - NOTCONTAINS -- app name does NOT contains given string (allowed flags: Re.IGNORECASE)
        - NOTSTARTSWITH -- app name does NOT starts by given string (allowed flags: Re.IGNORECASE)
        - NOTENDSWITH -- app name does NOT ends by given string (allowed flags: Re.IGNORECASE)
        - MATCH -- app name matched by given regex pattern (allowed flags: regex flags, see https://docs.python.org/3/library/re.html)
        - NOTMATCH -- app name NOT matched by given regex pattern (allowed flags: regex flags, see https://docs.python.org/3/library/re.html)
        - EDITDISTANCE -- app name matched using Levenshtein edit distance to a given similarity percentage (allowed flags: 0-100. Defaults to 90)
        - DIFFRATIO -- app name matched using difflib similarity ratio (allowed flags: 0-100. Defaults to 90)

    :param name: name or regex pattern to match, as string
    :param condition: (optional) condition to apply when searching the app. Defaults to ''Re.IS'' (is equal to)
    :param flags: (optional) specific flags to apply to condition. Defaults to 0 (no flags)
    :return: list of app names
    """
    matches = []
    if name and condition in Re._cond_dic.keys():
        lower = False
        if condition in (Re.MATCH, Re.NOTMATCH):
            name = re.compile(name, flags)
        elif condition in (Re.EDITDISTANCE, Re.DIFFRATIO):
            if not isinstance(flags, int) or not (0 < flags <= 100):
                flags = 90
        elif flags == Re.IGNORECASE:
            lower = True
            name = name.lower()
        for title in getAllAppsNames():
            if title and Re._cond_dic[condition](name, title.lower() if lower else title, flags):
                matches.append(title)
    return matches


def getAllAppsWindowsTitles() -> dict:
    """
    Get all visible apps names and their open windows titles

    Format:
        Key: app name

        Values: list of window titles as strings

    :return: python dictionary
    """
    process_list = _getAllApps(tryToFilter=True)
    result = {}
    for win in getAllWindows():
        pID = win32process.GetWindowThreadProcessId(win.getHandle())
        for item in process_list:
            appPID = item[0]
            appName = item[1]
            if appPID == pID[1]:
                if appName in result.keys():
                    result[appName].append(win.title)
                else:
                    result[appName] = [win.title]
                break
    return result


def getWindowsAt(x: int, y: int):
    """
    Get the list of Window objects whose windows contain the point ``(x, y)`` on screen

    :param x: X screen coordinate of the window(s)
    :param y: Y screen coordinate of the window(s)
    :return: list of Window objects
    """
    return [
        window for window
        in getAllWindows()
        if pointInRect(x, y, window.left, window.top, window.width, window.height)]


def getTopWindowAt(x: int, y: int):
    """
    Get the Window object at the top of the stack at the point ``(x, y)`` on screen

    :param x: X screen coordinate of the window
    :param y: Y screen coordinate of the window
    :return: Window object or None
    """
    hwnd: int = win32gui.WindowFromPoint((x, y))

    # Want to pull the parent window from the window handle
    # By using GetAncestor we are able to get the parent window instead of the owner window.
    while win32gui.IsChild(win32gui.GetParent(hwnd), hwnd):
        hwnd = ctypes.windll.user32.GetAncestor(hwnd, win32con.GA_ROOT)
    return Win32Window(hwnd) if hwnd else None


def _findWindowHandles(parent: int = None, window_class: str = None, title: str = None, onlyVisible: bool = False) -> List[int]:
    # https://stackoverflow.com/questions/56973912/how-can-i-set-windows-10-desktop-background-with-smooth-transition
    # Fixed: original post returned duplicated handles when trying to retrieve all windows (no class nor title)

    def _make_filter(class_name: str, title: str, onlyVisible=False):

        def enum_windows(handle: int, h_list: list):
            if class_name and class_name not in win32gui.GetClassName(handle):
                return True  # continue enumeration
            if title and title not in win32gui.GetWindowText(handle):
                return True  # continue enumeration
            if not onlyVisible or (onlyVisible and win32gui.IsWindowVisible(handle)):
                h_list.append(handle)

        return enum_windows

    cb = _make_filter(window_class, title, onlyVisible)
    try:
        handle_list = []
        if parent:
            win32gui.EnumChildWindows(parent, cb, handle_list)
        else:
            win32gui.EnumWindows(cb, handle_list)
        return handle_list
    except:
        return []


def _getAllApps(tryToFilter=False):
    # https://stackoverflow.com/questions/550653/cross-platform-way-to-get-pids-by-process-name-in-python
    WMI = GetObject('winmgmts:')
    processes = WMI.InstancesOf('Win32_Process')
    process_list = [(p.Properties_("ProcessID").Value, p.Properties_("Name").Value, p.Properties_("CommandLine").Value) for p in processes]
    if tryToFilter:
        # Trying to figure out how to identify user-apps (non-system apps). Commandline property seems to partially work
        matches = []
        for item in process_list:
            if item[2]:
                matches.append(item)
        process_list = matches
    return process_list


def _getWindowInfo(hWnd):

    class tagWINDOWINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD),
            ('rcWindow', wintypes.RECT),
            ('rcClient', wintypes.RECT),
            ('dwStyle', wintypes.DWORD),
            ('dwExStyle', wintypes.DWORD),
            ('dwWindowStatus', wintypes.DWORD),
            ('cxWindowBorders', wintypes.UINT),
            ('cyWindowBorders', wintypes.UINT),
            ('atomWindowType', wintypes.ATOM),
            ('wCreatorVersion', wintypes.WORD)
        ]

    PWINDOWINFO = ctypes.POINTER(tagWINDOWINFO)
    LPWINDOWINFO = ctypes.POINTER(tagWINDOWINFO)
    WINDOWINFO = tagWINDOWINFO
    wi = tagWINDOWINFO()
    wi.cbSize = ctypes.sizeof(wi)
    try:
        ctypes.windll.user32.GetWindowInfo(hWnd, ctypes.byref(wi))
    except:
        wi = None

    # None of these seem to return the right value, at least not in my system, but might be useful for other metrics
    # xBorder = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CXBORDER)
    # xEdge = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CXEDGE)
    # xSFrame = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CXSIZEFRAME)
    # xFFrame = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CXFIXEDFRAME)
    # hSscrollXSize = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CXHSCROLL)
    # hscrollYSize = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CYHSCROLL)
    # vScrollXSize = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CXVSCROLL)
    # vScrollYSize = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CYVSCROLL)
    # menuSize = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CYMENUSIZE)
    # titleSize = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CYCAPTION)
    return wi


class Win32Window(BaseWindow):
    def __init__(self, hWnd: int):
        super().__init__()
        self._hWnd = hWnd
        self._setupRectProperties()
        self._parent = win32gui.GetParent(self._hWnd)
        self._t = None
        self.menu = self._Menu(self)
        self.watchdog = self._WatchDog(self)

    def _getWindowRect(self) -> Rect:
        ctypes.windll.user32.SetProcessDPIAware()
        x, y, r, b = win32gui.GetWindowRect(self._hWnd)
        return Rect(x, y, r, b)

    def getExtraFrameSize(self, includeBorder: bool = True) -> Tuple[int, int, int, int]:
        """
        Get the invisible space, in pixels, around the window, including or not the visible resize border (usually 1px)
        This can be useful to accurately adjust window position and size to the desired visible space
        WARNING: Windows seems to only use this offset in the X coordinates, but not in the Y ones

        :param includeBorder: set to ''False'' to avoid including resize border (usually 1px) as part of frame size
        :return: (left, top, right, bottom) frame size as a tuple of int
        """
        wi = _getWindowInfo(self._hWnd)
        xOffset = 0
        yOffset = 0
        if wi:
            xOffset = wi.cxWindowBorders
            yOffset = wi.cyWindowBorders
        if not includeBorder:
            try:
                xBorder = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CXBORDER)
                yBorder = ctypes.windll.user32.GetSystemMetrics(win32con.SM_CYBORDER)
            except:
                xBorder = 1
                yBorder = 1
            xOffset -= xBorder
            yOffset -= yBorder

        return xOffset, yOffset, xOffset, yOffset

    def getClientFrame(self):
        """
        Get the client area of window, as a Rect (x, y, right, bottom)
        Notice that scroll and status bars might be included, or not, depending on the application

        :return: Rect struct
        """
        wi = _getWindowInfo(self._hWnd)
        rcClient = self._rect
        if wi:
            rcClient = wi.rcClient
        return Rect(rcClient.left, rcClient.top, rcClient.right, rcClient.bottom)

    def __repr__(self):
        return '%s(hWnd=%s)' % (self.__class__.__name__, self._hWnd)

    def __eq__(self, other):
        return isinstance(other, Win32Window) and self._hWnd == other._hWnd

    def close(self) -> bool:
        """
        Closes this window. This may trigger "Are you sure you want to
        quit?" dialogs or other actions that prevent the window from
        actually closing. This is identical to clicking the X button on the
        window.

        :return: ''True'' if window is closed
        """
        win32gui.PostMessage(self._hWnd, win32con.WM_CLOSE, 0, 0)
        return not win32gui.IsWindow(self._hWnd)

    def minimize(self, wait: bool = False) -> bool:
        """
        Minimizes this window

        :param wait: set to ''True'' to confirm action requested (in a reasonable time)
        :return: ''True'' if window minimized
        """
        if not self.isMinimized:
            win32gui.ShowWindow(self._hWnd, win32con.SW_MINIMIZE)
            retries = 0
            while wait and retries < WAIT_ATTEMPTS and not self.isMinimized:
                retries += 1
                time.sleep(WAIT_DELAY * retries)
        return self.isMinimized

    def maximize(self, wait: bool = False) -> bool:
        """
        Maximizes this window

        :param wait: set to ''True'' to confirm action requested (in a reasonable time)
        :return: ''True'' if window maximized
        """
        if not self.isMaximized:
            win32gui.ShowWindow(self._hWnd, win32con.SW_MAXIMIZE)
            retries = 0
            while wait and retries < WAIT_ATTEMPTS and not self.isMaximized:
                retries += 1
                time.sleep(WAIT_DELAY * retries)
        return self.isMaximized

    def restore(self, wait: bool = False) -> bool:
        """
        If maximized or minimized, restores the window to it's normal size

        :param wait: set to ''True'' to confirm action requested (in a reasonable time)
        :return: ''True'' if window restored
        """
        win32gui.ShowWindow(self._hWnd, win32con.SW_RESTORE)
        retries = 0
        while wait and retries < WAIT_ATTEMPTS and (self.isMaximized or self.isMinimized):
            retries += 1
            time.sleep(WAIT_DELAY * retries)
        return not self.isMaximized and not self.isMinimized

    def show(self, wait: bool = False) -> bool:
        """
        If hidden or showing, shows the window on screen and in title bar

        :param wait: set to ''True'' to wait until action is confirmed (in a reasonable time lap)
        :return: ''True'' if window showed
        """
        win32gui.ShowWindow(self._hWnd, win32con.SW_SHOW)
        retries = 0
        while wait and retries < WAIT_ATTEMPTS and not self.isVisible:
            retries += 1
            time.sleep(WAIT_DELAY * retries)
        return self.isVisible

    def hide(self, wait: bool = False) -> bool:
        """
        If hidden or showing, hides the window from screen and title bar

        :param wait: set to ''True'' to wait until action is confirmed (in a reasonable time lap)
        :return: ''True'' if window hidden
        """
        win32gui.ShowWindow(self._hWnd, win32con.SW_HIDE)
        retries = 0
        while wait and retries < WAIT_ATTEMPTS and self.isVisible:
            retries += 1
            time.sleep(WAIT_DELAY * retries)
        return not self.isVisible

    def activate(self, wait: bool = False) -> bool:
        """
        Activate this window and make it the foreground (focused) window

        :param wait: set to ''True'' to wait until action is confirmed (in a reasonable time lap)
        :return: ''True'' if window activated
        """
        win32gui.SetForegroundWindow(self._hWnd)
        return self.isActive

    def resize(self, widthOffset: int, heightOffset: int, wait: bool = False) -> bool:
        """
        Resizes the window relative to its current size

        :param widthOffset: offset to add to current window width as target width
        :param heightOffset: offset to add to current window height as target height
        :param wait: set to ''True'' to wait until action is confirmed (in a reasonable time lap)
        :return: ''True'' if window resized to the given size
        """
        return self.resizeTo(self.width + widthOffset, self.height + heightOffset, wait)

    resizeRel = resize  # resizeRel is an alias for the resize() method.

    def resizeTo(self, newWidth: int, newHeight: int, wait: bool = False) -> bool:
        """
        Resizes the window to a new width and height

        :param newWidth: target window width
        :param newHeight: target window height
        :param wait: set to ''True'' to wait until action is confirmed (in a reasonable time lap)
        :return: ''True'' if window resized to the given size
        """
        result = win32gui.MoveWindow(self._hWnd, self.left, self.top, newWidth, newHeight, True)
        retries = 0
        while result != 0 and wait and retries < WAIT_ATTEMPTS and (self.width != newWidth or self.height != newHeight):
            retries += 1
            time.sleep(WAIT_DELAY * retries)
        return self.width == newWidth and self.height == newHeight

    def move(self, xOffset: int, yOffset: int, wait: bool = False) -> bool:
        """
        Moves the window relative to its current position

        :param xOffset: offset relative to current X coordinate to move the window to
        :param yOffset: offset relative to current Y coordinate to move the window to
        :param wait: set to ''True'' to wait until action is confirmed (in a reasonable time lap)
        :return: ''True'' if window moved to the given position
        """
        return self.moveTo(self.left + xOffset, self.top + yOffset, wait)

    moveRel = move  # moveRel is an alias for the move() method.

    def moveTo(self, newLeft:int, newTop: int, wait: bool = False) -> bool:
        """
        Moves the window to new coordinates on the screen.
        In a multi-display environment, you can move the window to a different monitor using the coordinates
        returned by getAllScreens()

        :param newLeft: target X coordinate to move the window to
        :param newLeft: target Y coordinate to move the window to
        :param wait: set to ''True'' to wait until action is confirmed (in a reasonable time lap)
        :return: ''True'' if window moved to the given position
        """
        result = win32gui.MoveWindow(self._hWnd, newLeft, newTop, self.width, self.height, True)
        retries = 0
        while result != 0 and wait and retries < WAIT_ATTEMPTS and (self.left != newLeft or self.top != newTop):
            retries += 1
            time.sleep(WAIT_DELAY * retries)
        return self.left == newLeft and self.top == newTop

    def _moveResizeTo(self, newLeft: int, newTop: int, newWidth: int, newHeight: int) -> bool:
        win32gui.MoveWindow(self._hWnd, newLeft, newTop, newWidth, newHeight, True)
        return newLeft == self.left and newTop == self.top and newWidth == self.width and newHeight == self.height

    def alwaysOnTop(self, aot: bool = True) -> bool:
        """
        Keeps window on top of all others.

        :param aot: set to ''False'' to deactivate always-on-top behavior
        :return: ''True'' if command succeeded
        """
        if self._t and self._t.is_alive():
            self._t.kill()
        # https://stackoverflow.com/questions/25381589/pygame-set-window-on-top-without-changing-its-position/49482325 (kmaork)
        zorder = win32con.HWND_TOPMOST if aot else win32con.HWND_NOTOPMOST
        result = win32gui.SetWindowPos(self._hWnd, zorder, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        return result != 0

    def alwaysOnBottom(self, aob: bool = True) -> bool:
        """
        Keeps window below of all others, but on top of desktop icons and keeping all window properties

        :param aob: set to ''False'' to deactivate always-on-bottom behavior
        :return: ''True'' if command succeeded
        """
        ret = False
        if aob:
            result = win32gui.SetWindowPos(self._hWnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                           win32con.SWP_NOSENDCHANGING | win32con.SWP_NOOWNERZORDER | win32con.SWP_ASYNCWINDOWPOS | win32con.SWP_NOSIZE | win32con.SWP_NOMOVE | win32con.SWP_NOACTIVATE | win32con.SWP_NOREDRAW | win32con.SWP_NOCOPYBITS)
            if result != 0:
                # There is no HWND_TOPBOTTOM (similar to TOPMOST), so it won't keep window below all others as desired
                # May be catching WM_WINDOWPOSCHANGING event? Not sure if possible for a "foreign" window, and seems really complex
                # https://stackoverflow.com/questions/64529896/attach-keyboard-hook-to-specific-window
                # TODO: Try to find other smarter methods to keep window at the bottom
                ret = True
                if self._t is None:
                    self._t = _SendBottom(self._hWnd)
                    # Not sure about the best behavior: stop thread when program ends or keeping sending window below
                    self._t.setDaemon(True)
                    self._t.start()
                else:
                    self._t.restart()
        else:
            self._t.kill()
            ret = self.sendBehind(sb=False)
        return ret

    def lowerWindow(self) -> bool:
        """
        Lowers the window to the bottom so that it does not obscure any sibling windows

        :return: ''True'' if window lowered
        """
        result = win32gui.SetWindowPos(self._hWnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                       win32con.SWP_NOSIZE | win32con.SWP_NOMOVE | win32con.SWP_NOACTIVATE)
        return result != 0

    def raiseWindow(self) -> bool:
        """
        Raises the window to top so that it is not obscured by any sibling windows.

        :return: ''True'' if window raised
        """
        result = win32gui.SetWindowPos(self._hWnd, win32con.HWND_TOP, 0, 0, 0, 0,
                                       win32con.SWP_NOSIZE | win32con.SWP_NOMOVE | win32con.SWP_NOACTIVATE)
        return result != 0

    def sendBehind(self, sb: bool = True) -> bool:
        """
        Sends the window to the very bottom, below all other windows, including desktop icons.
        It may also cause that the window does not accept focus nor keyboard/mouse events as well as
        make the window disappear from taskbar and/or pager.

        :param sb: set to ''False'' to bring the window back to front
        :return: ''True'' if window sent behind desktop icons
        """
        if sb:
            def getWorkerW():

                thelist = []

                def findit(hwnd, ctx):
                    p = win32gui.FindWindowEx(hwnd, None, "SHELLDLL_DefView", "")
                    if p != 0:
                        thelist.append(win32gui.FindWindowEx(None, hwnd, "WorkerW", ""))

                win32gui.EnumWindows(findit, None)
                return thelist

            # https://www.codeproject.com/Articles/856020/Draw-Behind-Desktop-Icons-in-Windows-plus
            progman = win32gui.FindWindow("Progman", None)
            win32gui.SendMessageTimeout(progman, 0x052C, 0, 0, win32con.SMTO_NORMAL, 1000)
            workerw = getWorkerW()
            result = 0
            if workerw:
                result = win32gui.SetParent(self._hWnd, workerw[0])
        else:
            result = win32gui.SetParent(self._hWnd, self._parent)
            win32gui.DefWindowProc(self._hWnd, 0x0128, 3 | 0x4, 0)
            # Window raises, but completely transparent
            # Sometimes this fixes it, but not always
            # result = result | win32gui.ShowWindow(self._hWnd, win32con.SW_SHOWNORMAL)
            # win32gui.SetLayeredWindowAttributes(self._hWnd, win32api.RGB(255, 255, 255), 255, win32con.LWA_COLORKEY)
            # win32gui.SetWindowPos(self._hWnd, win32con.HWND_TOP, self.left, self.top, self.width, self.height, False)
            # win32gui.UpdateWindow(self._hWnd)
            # Didn't find a better way to update window content by the moment (also tried redraw(), update(), ...)
            # TODO: Find another way to properly update window
            self.hide()
            result = result | win32gui.ShowWindow(self._hWnd, win32con.SW_MINIMIZE)
            result = result | win32gui.ShowWindow(self._hWnd, win32con.SW_RESTORE)
            self.show()
        return result != 0

    def getAppName(self) -> str:
        """
        Get the name of the app current window belongs to

        :return: name of the app as string
        """
        # https://stackoverflow.com/questions/550653/cross-platform-way-to-get-pids-by-process-name-in-python
        WMI = GetObject('winmgmts:')
        processes = WMI.InstancesOf('Win32_Process')
        process_list = [(p.Properties_("ProcessID").Value, p.Properties_("Name").Value) for p in processes]
        pID = win32process.GetWindowThreadProcessId(self._hWnd)
        pID = pID[1]
        name = ""
        for item in process_list:
            if item[0] == pID:
                name = item[1]
        return name

    def getParent(self) -> int:
        """
        Get the handle of the current window parent. It can be another window or an application

        :return: handle of the window parent
        """
        return win32gui.GetParent(self._hWnd)

    def getChildren(self) -> List[int]:
        """
        Get the children handles of current window

        :return: list of handles
        """
        return _findWindowHandles(parent=self._hWnd)

    def getHandle(self) -> int:
        """
        Get the current window handle

        :return: window handle
        """
        return self._hWnd

    def isParent(self, child: int) -> bool:
        """
        Check if current window is parent of given window (handle)

        :param child: handle of the window you want to check if the current window is parent of
        :return: ''True'' if current window is parent of the given window
        """
        return win32gui.GetParent(child) == self._hWnd
    isParentOf = isParent  # isParentOf is an alias of isParent method

    def isChild(self, parent: int) -> bool:
        """
        Check if current window is child of given window/app (handle)

        :param parent: handle of the window/app you want to check if the current window is child of
        :return: ''True'' if current window is child of the given window
        """
        return parent == self.getParent()
    isChildOf = isChild  # isChildOf is an alias of isParent method

    def getDisplay(self) -> str:
        """
        Get display name in which current window space is mostly visible

        :return: display name as string
        """
        name = ""
        try:
            hDpy = win32api.MonitorFromRect(self._getWindowRect())
            wInfo = win32api.GetMonitorInfo(hDpy)
            name = wInfo.get("Device", "")
        except:
            pass
        return name

    def _getContent(self):
        # https://stackoverflow.com/questions/14500026/python-how-to-get-the-text-label-from-another-program-window
        # Does not work with Terminal or Chrome. Besides, I don't think it can be done in Linux nor macOS

        content = []

        def findContent(childWindow):
            bufferSize = win32gui.SendMessage(childWindow, win32con.WM_GETTEXTLENGTH, 0, 0) * 2
            buf = win32gui.PyMakeBuffer(bufferSize)
            win32gui.SendMessage(childWindow, win32con.WM_GETTEXT, bufferSize, buf)
            a = buf.tobytes().decode('UTF-16', 'replace')
            if a:
                b = a.split("\r\n")
                content.append(b)

        children = self.getChildren()
        for child in children:
            findContent(child)
        return content


    @property
    def isMinimized(self) -> bool:
        """
        Check if current window is currently minimized

        :return: ``True`` if the window is minimized
        """
        return win32gui.IsIconic(self._hWnd) != 0

    @property
    def isMaximized(self) -> bool:
        """
        Check if current window is currently maximized

        :return: ``True`` if the window is maximized
        """
        state = win32gui.GetWindowPlacement(self._hWnd)
        return state[1] == win32con.SW_SHOWMAXIMIZED

    @property
    def isActive(self) -> bool:
        """
        Check if current window is currently the active, foreground window

        :return: ``True`` if the window is the active, foreground window
        """
        return win32gui.GetForegroundWindow() == self._hWnd

    @property
    def title(self) -> str:
        """
        Get the current window title, as string

        :return: title as a string
        """
        name = win32gui.GetWindowText(self._hWnd)
        if isinstance(name, bytes):
            name = name.decode()
        return name

    @property
    def visible(self) -> bool:
        """
        Check if current window is visible (minimized windows are also visible)

        :return: ``True`` if the window is currently visible
        """
        return win32gui.IsWindowVisible(self._hWnd) != 0

    isVisible = visible  # isVisible is an alias for the visible property.

    @property
    def isAlive(self) -> bool:
        """
        Check if window (and application) still exists (minimized and hidden windows are included as existing)

        :return: ''True'' if window exists
        """
        return win32gui.IsWindow(self._hWnd) != 0

    class _WatchDog:
        """
        Set a watchdog, in a separate Thread, to be notified when some window states change

        Notice that changes will be notified according to the window status at the very moment of instantiating this class

        IMPORTANT: This can be extremely slow in macOS Apple Script version

         Available methods:
        :meth start: Initialize and start watchdog and selected callbacks
        :meth updateCallbacks: Change the states this watchdog is hooked to
        :meth updateInterval: Change the interval to check changes
        :meth kill: Stop the entire watchdog and all its hooks
        :meth isAlive: Check if watchdog is running
        """
        def __init__(self, parent):
            self._watchdog = None
            self._parent = parent

        def start(self, isAliveCB=None, isActiveCB=None, isVisibleCB=None, isMinimizedCB=None,
                  isMaximizedCB=None, resizedCB=None, movedCB=None, changedTitleCB=None, changedDisplayCB=None,
                  interval=0.3):
            """
            Initialize and start watchdog and hooks (callbacks to be invoked when desired window states change)

            Notice that changes will be notified according to the window status at the very moment of execute start()

            The watchdog is asynchronous, so notifications will not be immediate (adjust interval value to your needs)

            The callbacks definition MUST MATCH their return value (boolean, string or (int, int))

            IMPORTANT: This can be extremely slow in macOS Apple Script version

            :param isAliveCB: callback to call if window is not alive. Set to None to not to watch this
                            Returns the new alive status value (False)
            :param isActiveCB: callback to invoke if window changes its active status. Set to None to not to watch this
                            Returns the new active status value (True/False)
            :param isVisibleCB: callback to invoke if window changes its visible status. Set to None to not to watch this
                            Returns the new visible status value (True/False)
            :param isMinimizedCB: callback to invoke if window changes its minimized status. Set to None to not to watch this
                            Returns the new minimized status value (True/False)
            :param isMaximizedCB: callback to invoke if window changes its maximized status. Set to None to not to watch this
                            Returns the new maximized status value (True/False)
            :param resizedCB: callback to invoke if window changes its size. Set to None to not to watch this
                            Returns the new size (width, height)
            :param movedCB: callback to invoke if window changes its position. Set to None to not to watch this
                            Returns the new position (x, y)
            :param changedTitleCB: callback to invoke if window changes its title. Set to None to not to watch this
                            Returns the new title (as string)
            :param changedDisplayCB: callback to invoke if window changes display. Set to None to not to watch this
                            Returns the new display name (as string)
            :param interval: set the interval to watch window changes. Default is 0.3 seconds
            """
            if self._watchdog is None:
                self._watchdog = _WinWatchDog(self._parent, isAliveCB, isActiveCB, isVisibleCB, isMinimizedCB,
                                              isMaximizedCB, resizedCB, movedCB, changedTitleCB, changedDisplayCB,
                                              interval)
                self._watchdog.setDaemon(True)
                self._watchdog.start()
            else:
                self._watchdog.restart(isAliveCB, isActiveCB, isVisibleCB, isMinimizedCB,
                                       isMaximizedCB, resizedCB, movedCB, changedTitleCB, changedDisplayCB,
                                       interval)

        def updateCallbacks(self, isAliveCB=None, isActiveCB=None, isVisibleCB=None, isMinimizedCB=None,
                                    isMaximizedCB=None, resizedCB=None, movedCB=None, changedTitleCB=None,
                                    changedDisplayCB=None):
            """
            Change the states this watchdog is hooked to

            The callbacks definition MUST MATCH their return value (boolean, string or (int, int))

            IMPORTANT: When updating callbacks, remember to set ALL desired callbacks or they will be deactivated

            IMPORTANT: Remember to set ALL desired callbacks every time, or they will be defaulted to None (and unhooked)

            :param isAliveCB: callback to call if window is not alive. Set to None to not to watch this
                            Returns the new alive status value (False)
            :param isActiveCB: callback to invoke if window changes its active status. Set to None to not to watch this
                            Returns the new active status value (True/False)
            :param isVisibleCB: callback to invoke if window changes its visible status. Set to None to not to watch this
                            Returns the new visible status value (True/False)
            :param isMinimizedCB: callback to invoke if window changes its minimized status. Set to None to not to watch this
                            Returns the new minimized status value (True/False)
            :param isMaximizedCB: callback to invoke if window changes its maximized status. Set to None to not to watch this
                            Returns the new maximized status value (True/False)
            :param resizedCB: callback to invoke if window changes its size. Set to None to not to watch this
                            Returns the new size (width, height)
            :param movedCB: callback to invoke if window changes its position. Set to None to not to watch this
                            Returns the new position (x, y)
            :param changedTitleCB: callback to invoke if window changes its title. Set to None to not to watch this
                            Returns the new title (as string)
            :param changedDisplayCB: callback to invoke if window changes display. Set to None to not to watch this
                            Returns the new display name (as string)
            """
            if self._watchdog:
                self._watchdog.updateCallbacks(isAliveCB, isActiveCB, isVisibleCB, isMinimizedCB, isMaximizedCB,
                                              resizedCB, movedCB, changedTitleCB, changedDisplayCB)

        def updateInterval(self, interval=0.3):
            """
            Change the interval to check changes

            :param interval: set the interval to watch window changes. Default is 0.3 seconds
            """
            if self._watchdog:
                self._watchdog.updateInterval(interval)

        def setTryToFind(self, tryToFind: bool):
            """
            In macOS Apple Script version, if set to ''True'' and in case title changes, watchdog will try to find
            a similar title within same application to continue monitoring it. It will stop if set to ''False'' or
            similar title not found.

            IMPORTANT:

            - It will have no effect in other platforms (Windows and Linux) and classes (MacOSNSWindow)
            - This behavior is deactivated by default, so you need to explicitly activate it

            :param tryToFind: set to ''True'' to try to find a similar title. Set to ''False'' to deactivate this behavior
            """
            pass

        def stop(self):
            """
            Stop the entire WatchDog and all its hooks
            """
            self._watchdog.kill()

        def isAlive(self):
            """Check if watchdog is running

            :return: ''True'' if watchdog is alive
            """
            try:
                alive = bool(self._watchdog and self._watchdog.is_alive())
            except:
                alive = False
            return alive

    class _Menu:

        def __init__(self, parent: BaseWindow):
            self._parent = parent
            self._hWnd = parent._hWnd
            self._hMenu = win32gui.GetMenu(self._hWnd)
            self._menuStructure = {}
            self._sep = "|&|"

        def getMenu(self, addItemInfo: bool = False) -> dict:
            """
            Loads and returns Menu options, sub-menus and related information, as dictionary.

            It is HIGHLY RECOMMENDED you pre-load the Menu struct by explicitly calling getMenu()
            before invoking any other action.

            :param addItemInfo: if ''True'', adds win32 MENUITEMINFO struct to the output
            :return: python dictionary with MENU struct

            Output Format:
                Key:
                    item (option or sub-menu) title

                Values:
                    "parent":
                        parent sub-menu handle (main menu handle for level-0 items)
                    "hSubMenu":
                        item handle (!= 0 for sub-menu items only)
                    "wID":
                        item ID (required for other actions, e.g. clickMenuItem())
                    "rect":
                        Rect struct of the menu item (relative to window position)
                    "item_info" (optional):
                        win32 MENUITEMINFO struct containing all available menu item info
                    "shortcut":
                        shortcut to menu item, if any
                    "entries":
                        sub-items within the sub-menu (if any)
            """

            def findit(parent: int, level: str = "", parentRect: Rect = None) -> None:

                option = self._menuStructure
                if level:
                    for section in level.split(self._sep)[1:]:
                        option = option[section]

                for i in range(win32gui.GetMenuItemCount(parent)):
                    item_info = self._getMenuItemInfo(hSubMenu=parent, itemPos=i)
                    text = item_info.text.split("\t")
                    title = (text[0].replace("&", "")) or "separator"
                    shortcut = "" if len(text) < 2 else text[1]
                    rect = self._getMenuItemRect(hSubMenu=parent, itemPos=i, relative=True, parentRect=parentRect)
                    option[title] = {"parent": parent, "hSubMenu": item_info.hSubMenu, "wID": item_info.wID,
                                     "shortcut": shortcut, "rect": rect, "entries": {}}
                    if addItemInfo:
                        option[title]["item_info"] = item_info
                    findit(item_info.hSubMenu, level + self._sep + title + self._sep + "entries", rect)

            if self._hMenu:
                findit(self._hMenu)
            return self._menuStructure

        def clickMenuItem(self, itemPath: list = None, wID: int = 0) -> bool:
            """
            Simulates a click on a menu item

            Notes:
                - It will not work for men/sub-menu entries
                - It will not work if selected option is disabled

            Use one of these input parameters to identify desired menu item:

            :param itemPath: desired menu option and predecessors as list (e.g. ["Menu", "SubMenu", "Item"]). Notice it is language-dependent, so it's better to fulfill it from MENU struct as returned by :meth: getMenu()
            :param wID: item ID within menu struct (as returned by getMenu() method)
            :return: ''True'' if menu item to click is correct and exists (not if it has already been clicked or it had any effect)
            """
            found = False
            itemID = 0
            if self._hMenu:
                if wID:
                    itemID = wID
                elif itemPath:
                    if not self._menuStructure:
                        self.getMenu()
                    option = self._menuStructure
                    for item in itemPath[:-1]:
                        if item in option.keys() and "entries" in option[item].keys():
                            option = option[item]["entries"]
                        else:
                            option = {}
                            break

                    if option and itemPath[-1] in option.keys() and "wID" in option[itemPath[-1]].keys():
                        itemID = option[itemPath[-1]]["wID"]

                if itemID:
                    win32gui.PostMessage(self._hWnd, win32con.WM_COMMAND, itemID, 0)
                    found = True

            return found

        def getMenuInfo(self, hSubMenu: int = 0) -> win32gui_struct.UnpackMENUINFO:
            """
            Returns the MENUINFO struct of the given sub-menu or main menu if none given

            :param hSubMenu: id of the sub-menu entry (as returned by getMenu() method)
            :return: win32 MENUINFO struct
            """
            if not hSubMenu:
                hSubMenu = self._hMenu

            menu_info = None
            if hSubMenu:
                buf = win32gui_struct.EmptyMENUINFO()
                win32gui.GetMenuInfo(self._hMenu, buf)
                menu_info = win32gui_struct.UnpackMENUINFO(buf)
            return menu_info

        def getMenuItemCount(self, hSubMenu: int = 0) -> int:
            """
            Returns the number of items within a menu (main menu if no sub-menu given)

            :param hSubMenu: id of the sub-menu entry (as returned by getMenu() method)
            :return: number of items as int
            """
            if not hSubMenu:
                hSubMenu = self._hMenu
            return win32gui.GetMenuItemCount(hSubMenu)

        def getMenuItemInfo(self, hSubMenu: int, wID: int) -> win32gui_struct.UnpackMENUITEMINFO:
            """
            Returns the MENUITEMINFO struct for the given menu item

            :param hSubMenu: id of the sub-menu entry (as returned by :meth: getMenu())
            :param wID: id of the window within menu struct (as returned by :meth: getMenu())
            :return: win32 MENUITEMINFO struct
            """
            item_info = None
            if self._hMenu:
                buf, extras = win32gui_struct.EmptyMENUITEMINFO()
                win32gui.GetMenuItemInfo(hSubMenu, wID, False, buf)
                item_info = win32gui_struct.UnpackMENUITEMINFO(buf)
            return item_info

        def _getMenuItemInfo(self, hSubMenu: int, itemPos: int) -> win32gui_struct.UnpackMENUITEMINFO:
            item_info = None
            if self._hMenu:
                buf, extras = win32gui_struct.EmptyMENUITEMINFO()
                win32gui.GetMenuItemInfo(hSubMenu, itemPos, True, buf)
                item_info = win32gui_struct.UnpackMENUITEMINFO(buf)
            return item_info

        def getMenuItemRect(self, hSubMenu: int, wID: int) -> Rect:
            """
            Get the Rect struct (left, top, right, bottom) of the given Menu option

            :param hSubMenu: id of the sub-menu entry (as returned by :meth: getMenu())
            :param wID: id of the window within menu struct (as returned by :meth: getMenu())
            :return: Rect struct
            """

            def findit(menu, hSubMenu, wID):

                menuFound = [{}]

                def findMenu(inMenu, hSubMenu):

                    for key in inMenu.keys():
                        if inMenu[key]["hSubMenu"] == hSubMenu:
                            menuFound[0] = inMenu[key]["entries"]
                            break
                        elif "entries" in inMenu[key].keys():
                            findMenu(inMenu[key]["entries"], hSubMenu)

                findMenu(menu, hSubMenu)
                subMenu = menuFound[0]
                itemPos = -1
                for key in subMenu.keys():
                    itemPos += 1
                    if subMenu[key]["wID"] == wID:
                        return itemPos
                return itemPos

            if not self._menuStructure and self._hMenu:
                self.getMenu()

            itemPos = findit(self._menuStructure, hSubMenu, wID)
            ret = Rect(0, 0, 0, 0)
            if self._hMenu and 0 <= itemPos < self.getMenuItemCount(hSubMenu=hSubMenu):
                [result, (x, y, r, b)] = win32gui.GetMenuItemRect(self._hWnd, hSubMenu, itemPos)
                if result != 0:
                    ret = Rect(x, y, r, b)
            return ret

        def _getMenuItemRect(self, hSubMenu: int, itemPos: int, parentRect: Rect = None, relative: bool = False) -> Rect:
            ret = None
            if self._hMenu and hSubMenu and 0 <= itemPos < self.getMenuItemCount(hSubMenu=hSubMenu):
                [result, (x, y, r, b)] = win32gui.GetMenuItemRect(self._hWnd, hSubMenu, itemPos)
                if result != 0:
                    if relative:
                        x = abs(abs(x) - abs(self._parent.left))
                        y = abs(abs(y) - abs(self._parent.top))
                        r = abs(abs(r) - abs(self._parent.left))
                        b = abs(abs(b) - abs(self._parent.top))
                    if parentRect:
                        x = parentRect.left
                    ret = Rect(x, y, r, b)
            return ret


class _SendBottom(threading.Thread):

    def __init__(self, hWnd, interval=0.5):
        threading.Thread.__init__(self)
        self._hWnd = hWnd
        self._interval = interval
        self._kill = threading.Event()

    def _isLast(self):
        # This avoids flickering and CPU consumption. Not very smart, but no other option found... by the moment
        h = win32gui.GetWindow(self._hWnd, win32con.GW_HWNDLAST)
        last = True
        while h != 0 and h != self._hWnd:
            h = win32gui.GetWindow(h, win32con.GW_HWNDPREV)
            # TODO: Find a way to filter user vs. system apps. It should be doable like in Task Manager!!!
            # not sure if this always guarantees these other windows are "system" windows (not user windows)
            if h != self._hWnd and win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) not in ("WorkerW", "Progman"):
                last = False
                break
        return last

    def run(self):
        while not self._kill.is_set() and win32gui.IsWindow(self._hWnd):
            if not self._isLast():
                win32gui.SetWindowPos(self._hWnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                      win32con.SWP_NOSENDCHANGING | win32con.SWP_NOOWNERZORDER | win32con.SWP_ASYNCWINDOWPOS | win32con.SWP_NOSIZE | win32con.SWP_NOMOVE | win32con.SWP_NOACTIVATE | win32con.SWP_NOREDRAW | win32con.SWP_NOCOPYBITS)
            self._kill.wait(self._interval)

    def kill(self):
        self._kill.set()

    def restart(self):
        self.kill()
        self._kill = threading.Event()
        self.run()


def getAllScreens() -> dict:
    """
    load all monitors plugged to the pc, as a dict

    :return: Monitors info as python dictionary

    Output Format:
        Key:
            Display name

        Values:
            "id":
                display index as returned by EnumDisplayDevices()
            "is_primary":
                ''True'' if monitor is primary (shows clock and notification area, sign in, lock, CTRL+ALT+DELETE screens...)
            "pos":
                Point(x, y) struct containing the display position ((0, 0) for the primary screen)
            "size":
                Size(width, height) struct containing the display size, in pixels
            "workarea":
                Rect(left, top, right, bottom) struct with the screen workarea, in pixels
            "scale":
                Scale ratio, as a tuple of (x, y) scale percentage
            "dpi":
                Dots per inch, as a tuple of (x, y) dpi values
            "orientation":
                Display orientation: 0 - Landscape / 1 - Portrait / 2 - Landscape (reversed) / 3 - Portrait (reversed)
            "frequency":
                Refresh rate of the display, in Hz
            "colordepth":
                Bits per pixel referred to the display color depth
    """
    # https://stackoverflow.com/questions/35814309/winapi-changedisplaysettingsex-does-not-work
    result = {}
    ctypes.windll.user32.SetProcessDPIAware()
    monitors = win32api.EnumDisplayMonitors()
    i = 0
    while True:
        try:
            dev = win32api.EnumDisplayDevices(None, i, 0)
        except:
            break

        if dev and dev.StateFlags & win32con.DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            try:
                # Device content: http://timgolden.me.uk/pywin32-docs/PyDISPLAY_DEVICE.html
                # Settings content: http://timgolden.me.uk/pywin32-docs/PyDEVMODE.html
                monitor_info = None
                monitor = None
                for mon in monitors:
                    monitor = mon[0].handle
                    monitor_info = win32api.GetMonitorInfo(monitor)
                    name = monitor_info.get("Device", None)
                    if name == dev.DeviceName:
                        break

                if monitor_info:
                    x, y, r, b = monitor_info.get("Monitor", (0, 0, 0, 0))
                    wx, wy, wr, wb = monitor_info.get("Work", (0, 0, 0, 0))
                    settings = win32api.EnumDisplaySettings(dev.DeviceName, win32con.ENUM_CURRENT_SETTINGS)
                    # values seem to be affected by the scale factor of the first display
                    wr, wb = wx + settings.PelsWidth + (wr - r), wy + settings.PelsHeight + (wb - b)
                    is_primary = ((x, y) == (0, 0))
                    r, b = x + settings.PelsWidth, y + settings.PelsHeight
                    pScale = ctypes.c_uint()
                    ctypes.windll.shcore.GetScaleFactorForMonitor(monitor, ctypes.byref(pScale))
                    scale = pScale.value
                    dpiX = ctypes.c_uint()
                    dpiY = ctypes.c_uint()
                    ctypes.windll.shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpiX), ctypes.byref(dpiY))
                    rot = settings.DisplayOrientation
                    freq = settings.DisplayFrequency
                    depth = settings.BitsPerPel

                    result[dev.DeviceName] = {
                        "id": i,
                        # "is_primary": monitor_info.get("Flags", 0) & win32con.MONITORINFOF_PRIMARY == 1,
                        "is_primary": is_primary,
                        "pos": Point(x, y),
                        "size": Size(r - x, b - y),
                        "workarea": Rect(wx, wy, wr, wb),
                        "scale": (scale, scale),
                        "dpi": (dpiX.value, dpiY.value),
                        "orientation": rot,
                        "frequency": freq,
                        "colordepth": depth
                    }
            except:
                print(traceback.format_exc())
        i += 1
    return result


def getMousePos():
    """
    Get the current (x, y) coordinates of the mouse pointer on screen, in pixels

    :return: Point struct
    """
    ctypes.windll.user32.SetProcessDPIAware()
    cursor = win32api.GetCursorPos()
    return Point(cursor[0], cursor[1])
cursor = getMousePos  # cursor is an alias for getMousePos


def getScreenSize(name: str = "") -> Size:
    """
    Get the width and height, in pixels, of the given screen, or main screen if no screen name provided or not found

    :param name: name of the screen as returned by getAllScreens() and getDisplay() methods.
    :return: Size struct or None
    """
    size = None
    screens = getAllScreens()
    for key in screens.keys():
        if (name and key == name) or (not name and screens[key]["is_primary"]):
            size = screens[key]["size"]
            break
    return size
resolution = getScreenSize  # resolution is an alias for getScreenSize


def getWorkArea(name: str = "") -> Rect:
    """
    Get the Rect struct (left, top, right, bottom), in pixels, of the working (usable by windows) area
    of the given screen,  or main screen if no screen name provided or not found

    :param name: name of the screen as returned by getAllScreens() and getDisplay() methods.
    :return: Rect struct or None
    """
    screens = getAllScreens()
    workarea = None
    for key in screens.keys():
        if (name and key == name) or (not name and screens[key]["is_primary"]):
            workarea = screens[key]["workarea"]
            break
    return workarea


def displayWindowsUnderMouse(xOffset: int = 0, yOffset: int = 0):
    """
    This function is meant to be run from the command line. It will
    automatically display the position of mouse pointer and the titles
    of the windows under it
    """
    print('Press Ctrl-C to quit.')
    if xOffset != 0 or yOffset != 0:
        print('xOffset: %s yOffset: %s' % (xOffset, yOffset))
    try:
        prevWindows = None
        while True:
            x, y = getMousePos()
            positionStr = 'X: ' + str(x - xOffset).rjust(4) + ' Y: ' + str(y - yOffset).rjust(4) + '  (Press Ctrl-C to quit)'
            windows = getWindowsAt(x, y)
            if windows != prevWindows:
                print('\n')
                prevWindows = windows
                for win in windows:
                    name = win.title
                    eraser = '' if len(name) >= len(positionStr) else ' ' * (len(positionStr) - len(name))
                    sys.stdout.write((name or ("<No Name> ID: " + str(win._hWnd))) + eraser + '\n')
            sys.stdout.write(positionStr)
            sys.stdout.write('\b' * len(positionStr))
            sys.stdout.flush()
            time.sleep(0.3)
    except KeyboardInterrupt:
        sys.stdout.write('\n\n')
        sys.stdout.flush()


def activeCB(active):
    print("NEW ACTIVE STATUS", active)


def movedCB(pos):
    print("NEW POS", pos)


def main():
    """Run this script from command-line to get windows under mouse pointer"""
    print("PLATFORM:", sys.platform)
    print("SCREEN SIZE:", resolution())
    print("ALL WINDOWS", getAllTitles())
    npw = getActiveWindow()
    print("ACTIVE WINDOW:", npw.title, "/", npw.box)
    print()
    displayWindowsUnderMouse(0, 0)


if __name__ == "__main__":
    main()
