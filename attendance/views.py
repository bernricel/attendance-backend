from django.http import Http404
from django.shortcuts import redirect
from django.views import View

from .services import build_webapp_scan_url, get_session_by_qr_token


class UniversalQrScanRedirectView(View):
    """
    Browser entry point for universal QR links.

    The backend owns the QR URL and token validation, then forwards valid scans
    to the web app confirmation route which already handles auth/login redirect.
    """

    def get(self, request, qr_token):
        session = get_session_by_qr_token((qr_token or "").strip())
        if not session:
            raise Http404("Invalid QR token. Session not found.")
        return redirect(build_webapp_scan_url(session.qr_token))
