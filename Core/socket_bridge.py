import socket
import threading
from datetime import datetime
class SocketBridge:
    
    def __init__(self, listen_port, on_message=None, verbose=False, super_verbose=False):
        self.listen_port = listen_port
        self.on_message = on_message
        self.verbose = verbose
        self.super_verbose = super_verbose
        self.running = True
        self._server_socket = None
        self._start_server()

    def _start_server(self):
        def handle_client(client_socket):
            while self.running:
                try:
                    message = client_socket.recv(1024).decode('utf-8')
                    if not message:
                        break
                    if self.verbose:
                        print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                        print(f"[SocketBridge:{self.listen_port}] Received: {message}")
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
                print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                print(f"[SocketBridge] Listening on port {self.listen_port}")
            while self.running:
                try:
                    client, _ = self._server_socket.accept()
                    threading.Thread(target=handle_client, args=(client,), daemon=True).start()
                except OSError:
                    break

        threading.Thread(target=server_thread, daemon=True).start()

    def send(self, target_port, message):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.connect(('localhost', target_port))
                client.send(message.encode('utf-8'))
            if self.verbose:
                print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                print(f"[SocketBridge] Sent to {target_port}: {message}")
        except ConnectionRefusedError:
            print(f"[SocketBridge] Target on port {target_port} is not running.")
        except Exception as e:
            print(f"[SocketBridge] Error sending to port {target_port}: {e}")

    def stop(self):
        self.running = False
        if self._server_socket:
            self._server_socket.close()
        if self.verbose:
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[SocketBridge] Stopped listening on port {self.listen_port}")