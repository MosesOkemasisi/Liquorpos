from django.urls import path

from . import views

urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("new/", views.product_create, name="product_create"),
    path("<int:pk>/", views.product_edit, name="product_edit"),
    path("<int:pk>/stock/", views.stock_adjust, name="stock_adjust"),
]
