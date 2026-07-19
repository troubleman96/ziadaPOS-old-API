from django.db import models

from apps.accounts.models import Store, User
from apps.core.models import BaseModel


class Expense(BaseModel):
    CATEGORY_RENT = "Rent"
    CATEGORY_UTILITIES = "Utilities"
    CATEGORY_SALARIES = "Salaries"
    CATEGORY_SUPPLIES = "Supplies"
    CATEGORY_TRANSPORT = "Transport"
    CATEGORY_MARKETING = "Marketing"
    CATEGORY_MAINTENANCE = "Maintenance"
    CATEGORY_LICENCES = "Licences & permits"
    CATEGORY_INSURANCE = "Insurance"
    CATEGORY_OTHER = "Other"

    CATEGORY_CHOICES = [
        (CATEGORY_RENT, "Rent"),
        (CATEGORY_UTILITIES, "Utilities"),
        (CATEGORY_SALARIES, "Salaries"),
        (CATEGORY_SUPPLIES, "Supplies"),
        (CATEGORY_TRANSPORT, "Transport"),
        (CATEGORY_MARKETING, "Marketing"),
        (CATEGORY_MAINTENANCE, "Maintenance"),
        (CATEGORY_LICENCES, "Licences & permits"),
        (CATEGORY_INSURANCE, "Insurance"),
        (CATEGORY_OTHER, "Other"),
    ]

    METHOD_CASH = "Cash"
    METHOD_MPESA = "M-Pesa"
    METHOD_TIGOPESA = "Tigo Pesa"
    METHOD_BANK = "Bank"
    METHOD_AIRTEL = "Airtel Money"

    METHOD_CHOICES = [
        (METHOD_CASH, "Cash"),
        (METHOD_MPESA, "M-Pesa"),
        (METHOD_TIGOPESA, "Tigo Pesa"),
        (METHOD_BANK, "Bank"),
        (METHOD_AIRTEL, "Airtel Money"),
    ]

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="expenses",
        help_text="Store where this expense was recorded.",
    )

    title = models.CharField(
        max_length=255,
        help_text="Description / name of this expense.",
    )

    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_OTHER,
        help_text="Expense category.",
    )

    amount = models.PositiveIntegerField(
        help_text="Expense amount in TZS.",
    )

    payment_method = models.CharField(
        max_length=20,
        choices=METHOD_CHOICES,
        default=METHOD_CASH,
        help_text="Method used for this payment.",
    )

    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Receipt or reference number.",
    )

    notes = models.TextField(
        blank=True,
        default="",
        help_text="Additional notes / description.",
    )

    receipt_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text="Link to a receipt photo.",
    )

    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses_recorded",
        help_text="Staff member who recorded this expense.",
    )

    class Meta:
        db_table = "expenses_expense"
        ordering = ["-created_at"]
        verbose_name = "Expense"
        verbose_name_plural = "Expenses"
        indexes = [
            models.Index(fields=["store", "category"], name="idx_exp_store_cat"),
            models.Index(fields=["store", "payment_method"], name="idx_exp_pay_meth"),
            models.Index(fields=["store", "created_at"], name="idx_exp_store_date"),
        ]

    def __str__(self):
        return f"Expense {self.id} — {self.category} — TZS {self.amount:,} ({self.title[:40]})"
