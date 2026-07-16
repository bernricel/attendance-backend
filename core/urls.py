"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from attendance.views import UniversalQrScanRedirectView


def assetlinks_json(request):
    return JsonResponse(
        [
            {
                "relation": [
                    "delegate_permission/common.handle_all_urls",
                ],
                "target": {
                    "namespace": "android_app",
                    "package_name": "ph.edu.ua.uacheckin",
                    "sha256_cert_fingerprints": [
                        "F1:28:D6:DF:F6:B1:B7:DC:BC:14:7C:A5:92:06:48:05:0F:36:A6:DD:10:86:85:2D:2B:24:97:62:82:E8:A4:69",
                    ],
                },
            },
        ],
        safe=False,
    )


urlpatterns = [
    path('admin/', admin.site.urls),
    path('.well-known/assetlinks.json', assetlinks_json, name='assetlinks-json'),
    path('scan/<str:qr_token>', UniversalQrScanRedirectView.as_view(), name='universal-qr-scan'),
    path('api/auth/', include('users.urls')),
    path('api/admin/', include('attendance.urls_admin')),
    path('api/attendance/', include('attendance.urls_faculty')),
]
