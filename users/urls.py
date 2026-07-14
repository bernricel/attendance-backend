from django.urls import path

from .views import (
    ActiveDepartmentListView,
    ActiveProgramListView,
    AdminLoginView,
    CompleteProfileView,
    GoogleLoginView,
    ProfileView,
)

urlpatterns = [
    path("google-login/", GoogleLoginView.as_view(), name="google-login"),
    path("admin-login/", AdminLoginView.as_view(), name="admin-login"),
    path("complete-profile/", CompleteProfileView.as_view(), name="complete-profile"),
    path("departments/", ActiveDepartmentListView.as_view(), name="active-departments"),
    path("departments/<int:department_id>/programs/", ActiveProgramListView.as_view(), name="active-programs"),
    path("profile/", ProfileView.as_view(), name="profile"),
]
