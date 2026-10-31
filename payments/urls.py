from django.urls import path

from . import views

# Note: the callback path deliberately avoids words like "mpesa"/"safaricom" because Daraja
# can reject callback URLs that contain them.
urlpatterns = [
    path("callback/<str:secret>/", views.callback, name="pay_callback"),
    path("status/<uuid:public_id>/", views.status, name="pay_status"),
    path("retry/<uuid:public_id>/", views.retry, name="pay_retry"),
    path("cancel/<uuid:public_id>/", views.cancel, name="pay_cancel"),
]
