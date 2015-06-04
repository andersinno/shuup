# -*- coding: utf-8 -*-
# This file is part of Shoop.
#
# Copyright (c) 2012-2015, Shoop Ltd. All rights reserved.
#
# This source code is licensed under the AGPLv3 license found in the
# LICENSE file in the root directory of this source tree.
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.text import camel_case_to_spaces
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView
from shoop.admin.toolbar import Toolbar, JavaScriptActionButton, URLActionButton, get_discard_button
from shoop.admin.utils.urls import get_model_url
from shoop.admin.utils.views import CreateOrUpdateView, add_create_or_change_message, get_create_or_change_title
from shoop.notify.admin_module.forms import ScriptItemEditForm
from shoop.notify.admin_module.utils import get_enum_choices_dict
from shoop.notify.base import Action, Condition, Event
from shoop.notify.enums import StepConditionOperator, StepNext
from shoop.utils.text import snake_case
from django.shortcuts import redirect
from shoop.notify.admin_module.forms import ScriptForm
from shoop.notify.models.script import Script
from django.utils.translation import ugettext_lazy as _


@csrf_exempt  # This is fine -- the editor itself saves naught
def script_item_editor(request):
    # This is a regular non-CBV view because the way it processes the data it received
    # would be more awkward to do in a CBV.
    request.POST = dict(request.POST.items())  # Make it mutable
    init_data_json = request.POST.pop("init_data")
    init_data = json.loads(init_data_json)
    item_class = {"action": Action, "condition": Condition}[init_data["itemType"]]
    form = ScriptItemEditForm(
        script_item=item_class.unserialize(init_data["data"], validate=False),
        event_class=Event.class_for_identifier(init_data["eventIdentifier"]),
        data=(request.POST if request.POST else None),
        files=(request.FILES if request.FILES else None)
    )
    form.initial = form.get_initial()
    context = {
        "form": form,
        "script_item": form.script_item,
        "event_class": form.event_class,
        "init_data": init_data_json,
    }
    if form.data and form.is_valid():
        try:
            form.save()
        except ValidationError as verr:
            form.add_error(None, verr)
        else:
            context["post_message"] = {"new_data": form.script_item.data}
            # Unbind so we'll use the initial data
            form.is_bound = False
            form.data = {}
            form.initial = form.get_initial()

    return render(request, "notify/admin/script_item_editor.jinja", context)


class ScriptAPI(object):
    def __init__(self, request, script):
        """
        :param request: Request
        :type request: django.http.HttpRequest
        :param script: Script
        :type script: shoop.notify.models.Script
        """
        self.request = request
        self.script = script

    def dispatch(self):
        data = json.loads(self.request.body.decode("UTF-8"))
        command = data.pop("command")
        func_name = "handle_%s" % snake_case(camel_case_to_spaces(command))
        func = getattr(self, func_name, None)
        if not callable(func):
            return JsonResponse({"error": "No handler: %s" % func_name})
        return func(data)

    def handle_get_data(self, data):
        return JsonResponse({
            "steps": self.script.get_serialized_steps(),
        })

    def handle_save_data(self, data):
        try:
            self.script.set_serialized_steps(data["steps"])
        except Exception as exc:
            if settings.DEBUG:
                raise
            return JsonResponse({"error": exc})
        self.script.save(update_fields=("_step_data",))
        return JsonResponse({"success": "Changes saved."})


class EditScriptContentView(DetailView):
    template_name = "notify/admin/script_content_editor.jinja"
    model = Script
    context_object_name = "script"

    def post(self, request, *args, **kwargs):
        return ScriptAPI(request, self.get_object()).dispatch()

    def get_context_data(self, **kwargs):
        context = super(EditScriptContentView, self).get_context_data(**kwargs)
        context["title"] = get_create_or_change_title(self.request, self.object)
        context["action_infos"] = Action.get_ui_info_map()
        context["condition_infos"] = Condition.get_ui_info_map()
        context["cond_op_names"] = get_enum_choices_dict(StepConditionOperator)
        context["step_next_names"] = get_enum_choices_dict(StepNext)
        context["toolbar"] = Toolbar([
            JavaScriptActionButton(
                text="Save", icon="fa fa-save", extra_css_class="btn-success",
                onclick="ScriptEditor.save();return false"
            ),
            get_discard_button(get_model_url(self.object, "edit"))
        ])
        return context


class EditScriptView(CreateOrUpdateView):
    model = Script
    form_class = ScriptForm
    template_name = "notify/admin/edit_script.jinja"
    context_object_name = "script"

    def get_context_data(self, **kwargs):
        context = super(EditScriptView, self).get_context_data(**kwargs)
        if self.object.pk:
            context["toolbar"] = Toolbar([
                URLActionButton(
                    text=_(u"Edit Script Contents..."),
                    icon="fa fa-pencil",
                    extra_css_class="btn-info",
                    url=reverse("shoop_admin:notify.script.edit-content", kwargs={"pk": self.object.pk})
                )
            ])
        return context

    def form_valid(self, form):
        is_new = (not self.object.pk)
        wf = form.save()
        if is_new:
            return redirect("shoop_admin:notify.script.edit-content", pk=wf.pk)
        else:
            add_create_or_change_message(self.request, self.object, is_new=is_new)
            return redirect("shoop_admin:notify.script.edit", pk=wf.pk)
