from django.contrib import admin

from .models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display  = ["title", "store", "tag_list", "created_by", "created_at"]
    list_filter   = ["store", "created_at"]
    search_fields = ["title", "content"]
    readonly_fields = ["id", "created_at", "updated_at", "date_label"]

    def tag_list(self, obj):
        return ", ".join(obj.tags) if obj.tags else "—"
    tag_list.short_description = "Tags"
