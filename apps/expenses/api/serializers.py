from rest_framework import serializers

from ..models import Expense


class ExpenseListSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            "id", "title", "category", "amount",
            "payment_method", "payment_reference",
            "notes", "recorded_by", "recorded_by_name",
            "receipt_url", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "recorded_by", "created_at", "updated_at"]

    def get_recorded_by_name(self, obj):
        if obj.recorded_by:
            return obj.recorded_by.get_full_name() or obj.recorded_by.username
        return None


class ExpenseDetailSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            "id", "store", "title", "category", "amount",
            "payment_method", "payment_reference",
            "notes", "receipt_url",
            "recorded_by", "recorded_by_name",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "store", "recorded_by", "created_at", "updated_at"]

    def get_recorded_by_name(self, obj):
        if obj.recorded_by:
            return obj.recorded_by.get_full_name() or obj.recorded_by.username
        return None


class CreateExpenseSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, help_text="Expense title.")
    category = serializers.ChoiceField(
        choices=Expense.CATEGORY_CHOICES,
        default=Expense.CATEGORY_OTHER,
        help_text="Expense category.",
    )
    amount = serializers.IntegerField(min_value=1, help_text="Amount in TZS.")
    payment_method = serializers.ChoiceField(
        choices=Expense.METHOD_CHOICES,
        default=Expense.METHOD_CASH,
        help_text="Payment method.",
    )
    payment_reference = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default="",
        help_text="Receipt or reference number.",
    )
    notes = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default="",
        help_text="Additional notes.",
    )
    receipt_url = serializers.URLField(
        max_length=500, required=False, allow_blank=True, default="",
        help_text="Receipt photo URL.",
    )


class UpdateExpenseInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    category = serializers.ChoiceField(
        choices=Expense.CATEGORY_CHOICES, required=False,
    )
    amount = serializers.IntegerField(min_value=1, required=False)
    payment_method = serializers.ChoiceField(
        choices=Expense.METHOD_CHOICES, required=False,
    )
    payment_reference = serializers.CharField(
        max_length=100, required=False, allow_blank=True,
    )
    notes = serializers.CharField(
        max_length=2000, required=False, allow_blank=True,
    )
