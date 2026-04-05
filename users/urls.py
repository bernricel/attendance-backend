from django.urls import path

from .views import CompleteProfileView, GoogleLoginView

urlpatterns = [
    path("google-login/", GoogleLoginView.as_view(), name="google-login"),
    path("complete-profile/", CompleteProfileView.as_view(), name="complete-profile"),
]
