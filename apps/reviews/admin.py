from django.contrib import admin

from .models import StoreReview


@admin.register(StoreReview)
class StoreReviewAdmin(admin.ModelAdmin):
    list_display  = ["organisation", "rating", "trigger", "is_public", "created_at"]
    list_filter   = ["rating", "is_public", "trigger"]
    search_fields = ["organisation__name", "title", "body"]
    list_editable = ["is_public"]
    readonly_fields = ["created_at", "updated_at"]