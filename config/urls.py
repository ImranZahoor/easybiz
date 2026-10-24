"""Tenant host URLs."""

from django.urls import path

from easybiz.core.api import api

urlpatterns = [path("api/", api.urls)]
