from django.contrib import admin
from django.urls import URLPattern, URLResolver, path

from . import views

urlpatterns: list[URLPattern | URLResolver] = [
    path("admin/", admin.site.urls),
    path("", views.HomeView.as_view(), name="home"),
]
