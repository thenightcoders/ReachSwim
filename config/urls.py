from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("account/", include("apps.accounts.urls", namespace="accounts")),
    path("dashboard/", include("apps.dashboard.urls", namespace="dashboard")),
    path("", include("apps.payments.urls", namespace="payments")),
    path("", include("apps.shop.urls", namespace="shop")),
    path("", include("apps.booking.urls", namespace="booking")),
    path("", include("apps.legal.urls", namespace="legal")),
    path("", include("apps.pages.urls", namespace="pages")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
