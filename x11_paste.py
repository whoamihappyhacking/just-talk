"""
X11 底层粘贴模块 - 使用 XTest 扩展

方案 B: PRIMARY + Shift+Insert
- 整个流程（设置 selection、发送组合键、响应请求）在同一后台线程内完成
- 避免阻塞主应用程序的事件循环（或者造成长达几秒的卡顿）
- 修复了跨 Display 连接导致无法响应该 SelectionRequest 的卡死问题
"""

import threading
import time
from typing import Optional

try:
    from Xlib import display, X, XK, Xatom
    from Xlib.ext import xtest
    from Xlib.protocol import event
    XLIB_AVAILABLE = True
except ImportError:
    XLIB_AVAILABLE = False


class X11Paste:
    """X11 底层粘贴实现 - 方案 B: PRIMARY + Shift+Insert"""

    def __init__(self):
        if not XLIB_AVAILABLE:
            raise RuntimeError("python-xlib not available")
        
        self._handler_thread: Optional[threading.Thread] = None
        self._stop_handler = False

    def paste(self, text: str) -> bool:
        """
        粘贴文本到当前焦点窗口
        
        启动一个后台线程完成全套粘贴流程，立即返回不阻塞主线程。

        Args:
            text: 要粘贴的文本

        Returns:
            如果成功启动流程返回 True，否则 False
        """
        if not XLIB_AVAILABLE:
            return False

        try:
            self.cleanup()
            
            self._stop_handler = False
            self._handler_thread = threading.Thread(
                target=self._paste_process,
                args=(text,),
                daemon=True
            )
            self._handler_thread.start()
            
            # 等待一小段时间，确保后台线程至少发出了按键
            # 这样可以在函数返回后调用方执行其他操作时，按键已经生效
            time.sleep(0.05)
            
            return True
        except Exception:
            return False

    def _paste_process(self, text: str):
        """后台线程中执行的完整粘贴流程"""
        disp: Optional[display.Display] = None
        owner_window = None
        selection_text = text.encode('utf-8')

        try:
            disp = display.Display()
            root = disp.screen().root

            atom_primary = disp.intern_atom("PRIMARY")
            atom_utf8 = disp.intern_atom("UTF8_STRING")
            atom_targets = disp.intern_atom("TARGETS")

            shift_keycode = disp.keysym_to_keycode(XK.XK_Shift_L)
            insert_keycode = disp.keysym_to_keycode(XK.XK_Insert)

            # 1. 创建 owner 窗口并接管 PRIMARY
            owner_window = root.create_window(
                0, 0, 1, 1, 0, X.CopyFromParent, X.InputOnly
            )
            owner_window.set_selection_owner(atom_primary, X.CurrentTime)
            disp.sync()

            actual_owner = disp.get_selection_owner(atom_primary)
            if actual_owner != owner_window:
                return  # 获取 ownership 失败

            # 2. 模拟 Shift+Insert 组合键
            xtest.fake_input(disp, X.KeyPress, shift_keycode)
            disp.sync()
            time.sleep(0.01)
            xtest.fake_input(disp, X.KeyPress, insert_keycode)
            disp.sync()
            time.sleep(0.01)
            xtest.fake_input(disp, X.KeyRelease, insert_keycode)
            disp.sync()
            time.sleep(0.01)
            xtest.fake_input(disp, X.KeyRelease, shift_keycode)
            disp.sync()

            # 3. 处理目标窗口发来的 SelectionRequest 事件
            start = time.time()
            timeout = 2.0
            handled = 0

            while not self._stop_handler and time.time() - start < timeout:
                if disp.pending_events():
                    ev = disp.next_event()
                    if ev.type == X.SelectionRequest:
                        self._respond_selection(
                            ev, disp, selection_text,
                            atom_utf8, atom_targets,
                        )
                        handled += 1
                        if handled >= 5:  # 处理足够多的请求后可提早退出
                            break
                    elif ev.type == X.SelectionClear:
                        # 其它窗口接管了 PRIMARY
                        break
                else:
                    time.sleep(0.01)

        except Exception:
            pass
        finally:
            if owner_window:
                try:
                    owner_window.destroy()
                except Exception:
                    pass
            if disp:
                try:
                    disp.flush()
                    disp.close()
                except Exception:
                    pass

    def _respond_selection(
        self,
        ev,
        disp: display.Display,
        selection_text: bytes,
        atom_utf8,
        atom_targets,
    ):
        """发送 SelectionNotify 响应请求"""
        target = ev.target
        prop = ev.property if ev.property else ev.target

        try:
            if target == atom_targets:
                ev.requestor.change_property(
                    prop, Xatom.ATOM, 32,
                    [atom_utf8, Xatom.STRING]
                )
            elif target in (atom_utf8, Xatom.STRING):
                ev.requestor.change_property(
                    prop, target, 8, selection_text
                )
            else:
                prop = X.NONE

            notify = event.SelectionNotify(
                time=ev.time,
                requestor=ev.requestor,
                selection=ev.selection,
                target=target,
                property=prop,
            )
            ev.requestor.send_event(notify)
            disp.flush()
        except Exception:
            try:
                reject = event.SelectionNotify(
                    time=ev.time,
                    requestor=ev.requestor,
                    selection=ev.selection,
                    target=target,
                    property=X.NONE,
                )
                ev.requestor.send_event(reject)
                disp.flush()
            except Exception:
                pass

    def cleanup(self):
        """清理当前的后台流程"""
        self._stop_handler = True
        if self._handler_thread and self._handler_thread.is_alive():
            # 这里不用 join 阻塞，让其在后台自行自然退出
            pass
        self._handler_thread = None


# 单例实例
_x11_paste: Optional[X11Paste] = None


def x11_paste(text: str) -> bool:
    """
    使用 X11 底层 API 粘贴文本（PRIMARY + Shift+Insert）
    """
    global _x11_paste

    if not XLIB_AVAILABLE:
        return False

    try:
        if _x11_paste is None:
            _x11_paste = X11Paste()
        return _x11_paste.paste(text)
    except Exception:
        if _x11_paste:
            _x11_paste.cleanup()
            _x11_paste = None
        return False


def is_available() -> bool:
    """检查 X11 粘贴是否可用"""
    return XLIB_AVAILABLE
