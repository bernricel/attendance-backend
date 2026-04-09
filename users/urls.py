from django.urls import path

from .views import AdminLoginView, CompleteProfileView, GoogleLoginView

urlpatterns = [
    path("google-login/", GoogleLoginView.as_view(), name="google-login"),
    path("admin-login/", AdminLoginView.as_view(), name="admin-login"),
    path("complete-profile/", CompleteProfileView.as_view(), name="complete-profile"),
]
