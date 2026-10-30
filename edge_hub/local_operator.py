"""Passwordless operator pages for the loopback console only."""
import ipaddress
import secrets

from fastapi import Request

from edge_hub.ui_shell import service_shell

LOCAL_OPERATOR_TOKEN = secrets.token_urlsafe(32)
PLACEHOLDER = '__LOCAL_OPERATOR_TOKEN__'


def local_console_request(request: Request) -> bool:
    try:
        loopback = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False
    host = request.headers.get('host', '').lower()
    return (loopback and host in {'127.0.0.1:8000', 'localhost:8000', '[::1]:8000'}
            and request.headers.get('origin', f'http://{host}') == f'http://{host}'
            and request.headers.get('sec-fetch-site', 'none') != 'cross-site')


def operator_page(source: str, request: Request) -> str:
    # Never inject the configured operator password. This capability expires on restart.
    return service_shell(source).replace(PLACEHOLDER, LOCAL_OPERATOR_TOKEN if local_console_request(request) else '')
