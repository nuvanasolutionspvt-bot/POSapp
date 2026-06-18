"""
URL configuration for pos_backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
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

from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from api.views import (
    subscription_admin_businesses,
    subscription_admin_logout,
    subscription_admin_panel,
    subscription_admin_register_business,
    subscription_owner_login,
)
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

schema_view = get_schema_view(
    openapi.Info(
        title="POS App API",
        default_version="v1",
        description="Backend APIs for the POS mobile app.",
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path("subscription-admin/login/", subscription_owner_login, name="subscription-owner-login"),
    path("subscription-admin/", subscription_admin_panel, name="subscription-admin-root"),
    path(
        "subscription-admin/register/",
        subscription_admin_register_business,
        name="subscription-admin-register-business",
    ),
    path(
        "subscription-admin/businesses/",
        subscription_admin_businesses,
        name="subscription-admin-businesses",
    ),
    path("subscription-admin/logout/", subscription_admin_logout, name="subscription-admin-logout-root"),
    path("api/", include("api.urls")),
    path(
        "swagger/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
