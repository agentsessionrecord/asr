"""AstrBot loads this file from its normal data/plugins directory."""
from weakref import WeakKeyDictionary

from astrbot.api.event import filter
from astrbot.api.star import Context, Star


class ASRRecorder(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.sessions = WeakKeyDictionary()
        self.observer = None
        try:
            from asr_plugin_core import Observer
            from asr_astrbot import Recorder
            self.observer = Observer(Recorder())
        except Exception:
            pass

    def submit(self, hook, message, **payload):
        try:
            sid = self.sessions.get(message)
            if sid and self.observer:
                self.observer.submit({"hook": hook, "session_id": sid, **payload})
        except Exception:
            pass

    @filter.on_llm_request()
    async def request(self, event, request):
        try:
            if request.conversation is not None:
                self.sessions[event] = request.conversation.cid
            self.submit("on_llm_request", event, prompt=request.prompt)
        except Exception:
            pass

    @filter.on_agent_begin()
    async def begin(self, event, run_context):
        self.submit("on_agent_begin", event)

    @filter.on_using_llm_tool()
    async def tool_start(self, event, tool, tool_args):
        try:
            self.submit("on_using_llm_tool", event, tool_name=tool.name, tool_args=tool_args)
        except Exception:
            pass

    @filter.on_llm_tool_respond()
    async def tool_end(self, event, tool, tool_args, tool_result):
        try:
            output = tool_result.model_dump(mode="json") if tool_result is not None else None
            self.submit("on_llm_tool_respond", event, tool_name=tool.name, tool_args=tool_args, tool_result=output)
        except Exception:
            pass

    @filter.on_agent_done()
    async def done(self, event, run_context, response):
        try:
            self.submit("on_agent_done", event, completion_text=response.completion_text if response else None)
        except Exception:
            pass
