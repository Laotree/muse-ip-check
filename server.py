#!/usr/bin/env python3
"""本地静态服务器:python3 server.py [端口],默认 8765。
用浏览器打开 http://localhost:8765/ 开始检测。"""
import os
import sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

DEFAULT_PORT = 8765


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 安静一点


def parse_port(argv):
    if len(argv) < 2:
        return DEFAULT_PORT
    if argv[1] in ("-h", "--help"):
        print("usage: python3 server.py [port]")
        raise SystemExit(0)
    try:
        port = int(argv[1])
    except ValueError:
        raise SystemExit(f"端口必须是数字:{argv[1]}")
    if not 1 <= port <= 65535:
        raise SystemExit("端口必须在 1-65535 之间")
    return port


def main():
    port = parse_port(sys.argv)
    # 站点根固定为脚本所在目录,避免在别处启动时服务错误的目录
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    srv = ThreadingHTTPServer(("127.0.0.1", port), NoCacheHandler)
    print(f"本地服务已启动：http://localhost:{port}/")
    print("在要检测的那台机器的浏览器里打开上面地址。按 Ctrl+C 停止。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
