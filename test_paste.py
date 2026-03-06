import sys
import time

def test_paste(text):
    from x11_paste import x11_paste, is_available
    
    if not is_available():
        print("x11_paste 模块不可用，可能缺少 Python Xlib 库")
        return False
        
    print(f"正在准备使用 x11_paste 发送文本: '{text}'")
    print("📢 请在接下来的 3 秒内，将光标激活到一个文本编辑器或终端中！")
    
    for i in range(3, 0, -1):
        print(f"{i}...")
        time.sleep(1)
        
    print("▶️ 发送粘贴指令...")
    start = time.time()
    
    # 执行粘贴
    result = x11_paste(text)
    
    elapsed = time.time() - start
    print(f"✅ x11_paste 函数已返回，耗时: {elapsed:.4f}秒 (应几乎为 0)")
    
    # 保持主程序运行一小段时间，以便后台线程有时间完成处理
    if result:
        print("⏳ 保持程序运行 5 秒以观察后台行为及目标窗口反应（看看有没有卡死）...")
        for i in range(5, 0, -1):
            time.sleep(1)
        print("\n测试结束")
    else:
        print("❌ 粘贴函数返回 False")
    
    return result

if __name__ == "__main__":
    test_paste("Hello 从 x11_paste 发来的测试文本! " + str(time.time()))
