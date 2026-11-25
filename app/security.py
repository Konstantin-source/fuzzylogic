"""Minimaler Zugriffsschutz für den internen Betrieb hinter HTTPS."""
import base64
import binascii
import hmac
import os
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse


def credentials_configured():
    user = os.getenv('APP_USERNAME', '')
    password = os.getenv('APP_PASSWORD', '')
    return bool(user and ':' not in user and len(password) >= 16 and password != 'replace_with_a_long_random_password')


def authenticated(header):
    try:
        scheme, encoded = header.split(' ', 1)
        if scheme.lower() != 'basic':
            return False
        decoded = base64.b64decode(encoded, validate=True).decode('utf-8')
        user, password = decoded.split(':', 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False
    expected_user = os.getenv('APP_USERNAME', '')
    expected_password = os.getenv('APP_PASSWORD', '')
    if not credentials_configured():
        return False
    # compare_digest verlangt für Zeichenketten ASCII; UTF-8-Bytes vermeiden dies.
    user_matches = hmac.compare_digest(user.encode('utf-8'), expected_user.encode('utf-8'))
    password_matches = hmac.compare_digest(password.encode('utf-8'), expected_password.encode('utf-8'))
    return user_matches and password_matches


def same_origin(request):
    if request.headers.get('sec-fetch-site', '').lower() == 'cross-site':
        return False
    origin = request.headers.get('origin')
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        return (parsed.scheme in ('http', 'https') and parsed.netloc.lower() == request.headers.get('host', '').lower()
                and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    return response


async def protect(request, call_next):
    if not same_origin(request):
        return security_headers(PlainTextResponse('Zugriff verweigert.', status_code=403))
    if not authenticated(request.headers.get('authorization', '')):
        response = PlainTextResponse('Anmeldung erforderlich.', status_code=401, headers={'WWW-Authenticate': 'Basic realm="Artikelsuche", charset="UTF-8"'})
        return security_headers(response)
    return security_headers(await call_next(request))
