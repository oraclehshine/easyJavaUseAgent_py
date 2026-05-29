import os
import ssl
import threading
from concurrent import futures
from http.server import BaseHTTPRequestHandler, HTTPServer

import grpc
from prometheus_client import start_http_server

from app.service import AgentBridgeService
import agent_bridge_pb2_grpc


class HealthHandler(BaseHTTPRequestHandler):
    service_ref = None

    def do_GET(self):
        if self.path == "/liveness":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path == "/readiness":
            ok = True
            detail = "ready"
            if HealthHandler.service_ref is not None:
                ok, detail = HealthHandler.service_ref.readiness()
            self.send_response(200 if ok else 503)
            self.end_headers()
            self.wfile.write(detail.encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()


def build_server_credentials():
    cert_path = os.getenv("AGENT_TLS_CERT_PATH", "")
    key_path = os.getenv("AGENT_TLS_KEY_PATH", "")
    ca_path = os.getenv("AGENT_TLS_CLIENT_CA_PATH", "")
    env = os.getenv("AGENT_ENV", "dev").lower()
    tls_default = "false" if env in ("dev", "local") else "true"
    tls_enabled = os.getenv("AGENT_TLS_ENABLED", tls_default).lower() == "true"
    mtls_enabled = os.getenv("AGENT_MTLS_ENABLED", "false").lower() == "true"
    allow_plaintext = os.getenv("AGENT_ALLOW_PLAINTEXT", "false").lower() == "true"

    if not tls_enabled:
        if not allow_plaintext:
            raise RuntimeError("TLS disabled but AGENT_ALLOW_PLAINTEXT is false")
        return None

    with open(key_path, "rb") as f:
        private_key = f.read()
    with open(cert_path, "rb") as f:
        cert_chain = f.read()

    root_cert = None
    require_client_auth = False
    if mtls_enabled:
        with open(ca_path, "rb") as f:
            root_cert = f.read()
        require_client_auth = True

    return grpc.ssl_server_credentials(
        [(private_key, cert_chain)],
        root_certificates=root_cert,
        require_client_auth=require_client_auth,
    )


def run_health_server():
    port = int(os.getenv("AGENT_HEALTH_PORT", "8089"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def main() -> None:
    start_http_server(int(os.getenv("AGENT_METRICS_PORT", "9102")))
    threading.Thread(target=run_health_server, daemon=True).start()

    max_workers = int(os.getenv("AGENT_GRPC_WORKERS", "16"))
    max_msg = int(os.getenv("AGENT_MAX_MESSAGE_BYTES", str(8 * 1024 * 1024)))

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers),
        options=[
            ("grpc.max_receive_message_length", max_msg),
            ("grpc.max_send_message_length", max_msg),
        ],
    )
    service = AgentBridgeService()
    HealthHandler.service_ref = service
    agent_bridge_pb2_grpc.add_AgentBridgeServiceServicer_to_server(service, server)

    bind_addr = os.getenv("AGENT_GRPC_BIND", "0.0.0.0:50051")
    creds = build_server_credentials()
    if creds is None:
        server.add_insecure_port(bind_addr)
        print(f"Python Agent gRPC server (plaintext) started at {bind_addr}")
    else:
        server.add_secure_port(bind_addr, creds)
        print(f"Python Agent gRPC server (TLS) started at {bind_addr}")

    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    main()
