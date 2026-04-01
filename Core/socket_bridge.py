import socket
import threading
from Core.log_utils import log


class SocketBridge:

    def __init__(self, listen_port, on_message=None, verbose=False, super_verbose=False):
        self.listen_port = listen_port
        self.on_message = on_message
        self.verbose = verbose
        self.super_verbose = super_verbose
        self.running = True
        self._server_socket = None
        self._out_socket = None
        self._out_lock = threading.Lock()
        self._start_server()

    def _start_server(self):
        def handle_client(client_socket):
            buffer = ""
            while self.running:
                try:
                    chunk = client_socket.recv(1024).decode('utf-8')
                    if not chunk:
                        break
                    buffer += chunk
                    while '\n' in buffer:
                        message, buffer = buffer.split('\n', 1)
                        message = message.strip()
                        if not message:
                            continue
                        if self.verbose:
                            log(f"[SocketBridge:{self.listen_port}] Received: {message}")
                        if self.on_message:
                            self.on_message(message)
                except Exception as e:
                    print(f"[SocketBridge:{self.listen_port}] Error: {e}")
                    break
            client_socket.close()

        def server_thread():
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(('localhost', self.listen_port))
            self._server_socket.listen(5)
            if self.verbose:
                log(f"[SocketBridge] Listening on port {self.listen_port}")
            while self.running:
                try:
                    client, _ = self._server_socket.accept()
                    threading.Thread(target=handle_client, args=(client,), daemon=True).start()
                except OSError:
                    break

        threading.Thread(target=server_thread, daemon=True).start()

    def send(self, target_port, message):
        with self._out_lock:
            try:
                if self._out_socket is None:
                    self._out_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self._out_socket.connect(('localhost', target_port))
                self._out_socket.send((message + '\n').encode('utf-8'))
                if self.verbose:
                    log(f"[SocketBridge] Sent to {target_port}: {message}")
            except ConnectionRefusedError:
                self._out_socket = None
                print(f"[SocketBridge] Target on port {target_port} is not running.")
            except Exception as e:
                self._out_socket = None
                print(f"[SocketBridge] Error sending to port {target_port}: {e}")

    def stop(self):
        self.running = False
        if self._server_socket:
            self._server_socket.close()
        with self._out_lock:
            if self._out_socket:
                self._out_socket.close()
                self._out_socket = None
        if self.verbose:
            log(f"[SocketBridge] Stopped listening on port {self.listen_port}")
