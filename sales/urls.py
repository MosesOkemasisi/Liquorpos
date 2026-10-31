from django.urls import path

from . import views

urlpatterns = [
    path("", views.pos, name="pos"),
    path("api/products/", views.api_products, name="api_products"),
    path("api/checkout/", views.api_checkout, name="api_checkout"),
    path("receipt/<uuid:public_id>/", views.receipt, name="receipt"),
    path("sales/", views.sale_list, name="sale_list"),
    path("sales/<int:pk>/", views.sale_detail, name="sale_detail"),
    path("sales/<int:pk>/void/", views.sale_void, name="sale_void"),
    path("sales/<int:pk>/fulfil/", views.sale_fulfil, name="sale_fulfil"),
]
