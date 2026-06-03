from django.urls import path

from .views import PublicReviewsView, SubmitReviewView

urlpatterns = [
    path("",        SubmitReviewView.as_view(),  name="review-submit"),
    path("public/", PublicReviewsView.as_view(), name="review-public"),
]
