from django.urls import path

from .views import ExpenseDetailView, ExpenseListView, ExpenseSummaryView

urlpatterns = [
    path("summary/", ExpenseSummaryView.as_view(), name="expense-summary"),
    path("<uuid:pk>/", ExpenseDetailView.as_view(), name="expense-detail"),
    path("", ExpenseListView.as_view(), name="expense-list"),
]
