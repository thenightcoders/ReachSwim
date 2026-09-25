"""
Declarative CRUD for dashboard sections.

A ``Crud`` subclass describes one model's list page (columns, search, filters,
sorting, bulk actions) and its create/edit form. ``Crud.urls()`` returns the
URL patterns, named ``<key>_list``, ``<key>_create``, ``<key>_edit``,
``<key>_delete``, ``<key>_bulk`` and ``<key>_toggle``.

Bespoke screens (bookings, orders, people, settings) stay as plain views in
views.py; this module only removes the boilerplate for straightforward models.
"""
from dataclasses import dataclass, field
from typing import Any, Callable

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import ProtectedError, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import owner_required


@dataclass
class Column:
    label: str
    attr: str | Callable[[Any], Any]
    # title  → bold link to the edit page      badge → status pill (value, css modifier)
    # money  → pence rendered as currency      bool  → Yes/No pill
    # toggle → clickable active/inactive pill   thumb → image + title link
    # date / datetime / muted / text
    kind: str = "text"
    sort: str | None = None
    sub: str | Callable[[Any], Any] | None = None  # secondary line under the value
    num: bool = False

    def _resolve(self, obj, attr):
        if callable(attr):
            return attr(obj)
        value = obj
        for part in attr.split("__"):
            value = getattr(value, part, None)
            if value is None:
                return None
        return value() if callable(value) else value

    def value(self, obj):
        return self._resolve(obj, self.attr)

    def sub_value(self, obj):
        return self._resolve(obj, self.sub) if self.sub else None


@dataclass
class Filter:
    param: str
    label: str
    choices: list | Callable[[], list]
    lookup: str | Callable[[Any, str], Any] = ""

    def get_choices(self):
        return self.choices() if callable(self.choices) else self.choices

    def apply(self, qs, value):
        if callable(self.lookup):
            return self.lookup(qs, value)
        return qs.filter(**{self.lookup or self.param: value})


@dataclass
class BulkAction:
    name: str
    label: str
    run: Callable[[Any, Any], str]  # (request, queryset) -> success message
    danger: bool = False
    confirm: str = ""


@dataclass
class Row:
    obj: Any
    cells: list = field(default_factory=list)
    dim: bool = False


class Crud:
    key: str = ""
    model = None
    form_class = None
    section: str = ""
    title: str = ""            # plural, e.g. "Vouchers"
    singular: str = ""         # e.g. "voucher"
    description: str = ""
    empty_text: str = ""
    columns: list[Column] = []
    search_fields: tuple = ()
    search_placeholder: str = "Search"
    filters: list[Filter] = []
    ordering: tuple = ()
    toggle_field: str | None = None
    per_page = 50
    can_create = True
    can_delete = True
    delete_warning: str = ""
    list_template = "dashboard/crud/list.html"
    form_template = "dashboard/crud/form.html"
    # Fieldsets for the form: [(title or None, [field names]), ...]. None → all fields in one panel.
    fieldsets: list | None = None
    # Fields shown in a collapsed "More options" panel.
    advanced_fields: tuple = ()
    # Optional sidebar partial rendered next to the form.
    form_side_template: str | None = None
    # Optional partial rendered under the main fields (e.g. inline pricing).
    form_extra_template: str | None = None
    help_tips: tuple = ()

    # -- hooks ------------------------------------------------------------

    def get_queryset(self, request):
        qs = self.model.objects.all()
        return qs.order_by(*self.ordering) if self.ordering else qs

    def get_form(self, request, instance=None):
        data = request.POST if request.method == "POST" else None
        files = request.FILES if request.method == "POST" else None
        return self.form_class(data, files, instance=instance)

    def get_formsets(self, request, instance):
        """Return a dict of name → formset for inline editing (e.g. footer links)."""
        return {}

    def extra_form_context(self, request, instance):
        return {}

    def after_save(self, request, obj, created):
        """Hook for saving related data posted alongside the main form."""

    def str_for(self, obj):
        return str(obj)

    def get_bulk_actions(self):
        actions = []
        if self.toggle_field:
            actions.append(BulkAction("activate", "Turn on", self._bulk_set(True)))
            actions.append(BulkAction("deactivate", "Turn off", self._bulk_set(False)))
        actions.extend(self.extra_bulk_actions())
        if self.can_delete:
            actions.append(BulkAction(
                "delete", "Delete", self._bulk_delete, danger=True,
                confirm=f"Delete the selected {self.title.lower()}? This can't be undone.",
            ))
        return actions

    def extra_bulk_actions(self):
        return []

    # -- helpers ----------------------------------------------------------

    # URL names, for {% url crud.edit_name pk %} in templates.
    list_name = property(lambda self: f"dashboard:{self.key}_list")
    create_name = property(lambda self: f"dashboard:{self.key}_create")
    edit_name = property(lambda self: f"dashboard:{self.key}_edit")
    delete_name = property(lambda self: f"dashboard:{self.key}_delete")
    bulk_name = property(lambda self: f"dashboard:{self.key}_bulk")
    toggle_name = property(lambda self: f"dashboard:{self.key}_toggle")

    def url(self, action, *args):
        return reverse(f"dashboard:{self.key}_{action}", args=args)

    def _bulk_set(self, value):
        def run(request, qs):
            n = qs.update(**{self.toggle_field: value})
            return f"{n} {self.title.lower()} turned {'on' if value else 'off'}."
        return run

    def _bulk_delete(self, request, qs):
        try:
            n = qs.count()
            qs.delete()
        except ProtectedError:
            raise ValueError(
                f"Some of these {self.title.lower()} are still in use (e.g. by orders or bookings) and can't be deleted. "
                "Turn them off instead."
            )
        return f"{n} {self.title.lower()} deleted."

    def _base_context(self, **extra):
        ctx = {"crud": self, "section": self.section}
        ctx.update(extra)
        return ctx

    # -- views ------------------------------------------------------------

    def list_view(self, request):
        qs = self.get_queryset(request)
        q = request.GET.get("q", "").strip()
        if q and self.search_fields:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)

        active_filters = {}
        for flt in self.filters:
            value = request.GET.get(flt.param, "")
            if value != "":
                qs = flt.apply(qs, value)
                active_filters[flt.param] = value

        sort = request.GET.get("o", "")
        sortable = {c.sort for c in self.columns if c.sort}
        if sort.lstrip("-") in sortable:
            qs = qs.order_by(sort)

        page_obj = Paginator(qs, self.per_page).get_page(request.GET.get("page"))
        rows = [
            Row(
                obj,
                [(c, c.value(obj), c.sub_value(obj)) for c in self.columns],
                dim=bool(self.toggle_field) and not getattr(obj, self.toggle_field),
            )
            for obj in page_obj
        ]

        return render(request, self.list_template, self._base_context(
            rows=rows,
            page_obj=page_obj,
            q=q,
            sort=sort,
            filter_widgets=[(f, f.get_choices(), request.GET.get(f.param, "")) for f in self.filters],
            is_filtered=bool(q or active_filters),
            bulk_actions=self.get_bulk_actions(),
            **self.extra_list_context(request),
        ))

    def extra_list_context(self, request):
        return {}

    def _form_view(self, request, instance=None):
        created = instance is None
        form = self.get_form(request, instance)
        formsets = self.get_formsets(request, instance or self.model())
        if request.method == "POST":
            if form.is_valid() and all(fs.is_valid() for fs in formsets.values()):
                obj = form.save()
                for fs in formsets.values():
                    fs.instance = obj
                    fs.save()
                self.after_save(request, obj, created)
                verb = "added" if created else "saved"
                messages.success(request, f"{self.singular.capitalize()} “{self.str_for(obj)}” {verb}.")
                if "_continue" in request.POST:
                    return redirect(self.url("edit", obj.pk))
                if "_addanother" in request.POST:
                    return redirect(self.url("create"))
                return redirect(self.url("list"))

        field_names = list(form.fields)
        advanced = [n for n in self.advanced_fields if n in form.fields]
        if self.fieldsets:
            groups = [(title, [form[n] for n in names if n in form.fields]) for title, names in self.fieldsets]
        else:
            groups = [(None, [form[n] for n in field_names if n not in advanced])]

        return render(request, self.form_template, self._base_context(
            form=form,
            formsets=formsets,
            groups=groups,
            advanced=[form[n] for n in advanced],
            object=instance,
            is_create=created,
            has_files=form.is_multipart(),
            **self.extra_form_context(request, instance),
        ))

    def create_view(self, request):
        if not self.can_create:
            raise Http404
        return self._form_view(request)

    def edit_view(self, request, pk):
        return self._form_view(request, get_object_or_404(self.get_queryset(request), pk=pk))

    def delete_view(self, request, pk):
        obj = get_object_or_404(self.model, pk=pk)
        label = self.str_for(obj)
        try:
            obj.delete()
            messages.success(request, f"{self.singular.capitalize()} “{label}” deleted.")
        except ProtectedError:
            messages.error(
                request,
                f"“{label}” is still used by existing orders or bookings, so it can't be deleted. "
                "Turn it off instead to hide it.",
            )
            return redirect(self.url("edit", pk))
        return redirect(self.url("list"))

    def bulk_view(self, request):
        ids = request.POST.getlist("ids")
        action = next((a for a in self.get_bulk_actions() if a.name == request.POST.get("action")), None)
        if not ids or action is None:
            messages.warning(request, "Select at least one row, then choose an action.")
        else:
            try:
                messages.success(request, action.run(request, self.model.objects.filter(pk__in=ids)))
            except ValueError as exc:
                messages.error(request, str(exc))
        return redirect(request.POST.get("next") or self.url("list"))

    def toggle_view(self, request, pk):
        obj = get_object_or_404(self.model, pk=pk)
        setattr(obj, self.toggle_field, not getattr(obj, self.toggle_field))
        obj.save(update_fields=[self.toggle_field])
        state = "on" if getattr(obj, self.toggle_field) else "off"
        messages.success(request, f"“{self.str_for(obj)}” turned {state}.")
        return redirect(request.POST.get("next") or self.url("list"))

    # -- routing ----------------------------------------------------------

    @classmethod
    def urls(cls, prefix=None):
        inst = cls()
        p = prefix or f"{cls.key}s"
        k = cls.key
        patterns = [
            path(f"{p}/", owner_required(inst.list_view), name=f"{k}_list"),
            path(f"{p}/<int:pk>/edit/", owner_required(inst.edit_view), name=f"{k}_edit"),
            path(f"{p}/<int:pk>/delete/", owner_required(require_POST(inst.delete_view)), name=f"{k}_delete"),
            path(f"{p}/bulk/", owner_required(require_POST(inst.bulk_view)), name=f"{k}_bulk"),
        ]
        if cls.can_create:
            patterns.append(path(f"{p}/new/", owner_required(inst.create_view), name=f"{k}_create"))
        if cls.toggle_field:
            patterns.append(path(f"{p}/<int:pk>/toggle/", owner_required(require_POST(inst.toggle_view)), name=f"{k}_toggle"))
        return patterns
