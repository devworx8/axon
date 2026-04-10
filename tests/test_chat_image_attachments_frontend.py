from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_RUNS_JS = ROOT / "ui/js/workspace-runs.js"
CHAT_JS = ROOT / "ui/js/chat.js"
IMAGE_VIEWER_JS = ROOT / "ui/js/image-viewer.js"


def _run_script(files: list[Path], body: str):
    load_scripts = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(path))}, 'utf8'), ctx);"
        for path in files
    )
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          window: {{}},
          Blob,
          FormData,
          console,
          requestAnimationFrame: (fn) => fn(),
          setTimeout,
          clearTimeout,
        }};
        ctx.globalThis = ctx;
        vm.createContext(ctx);
        {load_scripts}
        (async () => {{
          {body}
        }})().catch((error) => {{
          console.error(error);
          process.exit(1);
        }});
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class ChatImageAttachmentsFrontendTests(unittest.TestCase):
    def test_send_chat_uploads_image_resources_before_streaming(self):
        payload = _run_script(
            [WORKSPACE_RUNS_JS, CHAT_JS],
            """
            const app = {
              chatProjectId: '7',
              chatInput: 'Review this mobile screenshot',
              chatMessages: [],
              chatLoading: false,
              businessMode: false,
              agentMode: false,
              selectedResources: [{ id: 15, title: 'Support brief' }],
              composerOptions: { pin_context: false },
              imageAttachments: [{ id: 'img-1', name: 'mobile.png', dataUrl: 'data:image/png;base64,xyz', file: { name: 'mobile.png' } }],
              currentResearchPack() {
                return { resources: [{ id: 12, title: 'Acceptance checklist' }] };
              },
              mergeUniqueResources(items) { return items; },
              resolveChatMode() { return 'chat'; },
              usesOllamaBackend() { return false; },
              rememberComposerHistory(message) {
                this.history = [...(this.history || []), message];
              },
              resetChatComposerHeight() {},
              scrollChat() {},
              setAgentStage(stage) { this.stage = stage; },
              beginLiveOperator() {},
              updateLiveOperator() {},
              clearLiveOperator() {},
              showToast(message) { this.toast = message; },
              createAssistantPlaceholder(respId, mode, retryResources = []) {
                return { id: respId, role: 'assistant', content: '', streaming: true, mode, retryResources };
              },
              async uploadImageAttachments(options = {}) {
                this.uploadOptions = {
                  workspaceId: options.workspaceId,
                  attachmentNames: (options.attachments || []).map((item) => item.name),
                };
                return [{ id: 77, title: 'mobile', kind: 'image' }];
              },
              clearImageAttachments() {
                this.imageAttachments = [];
                this.imagesCleared = true;
              },
              async streamChatMessage(message, mode, respId, resourceIds, extraPayload, workspaceId) {
                this.streamPayload = { message, mode, respId, resourceIds, extraPayload, workspaceId };
              },
            };

            Object.assign(
              app,
              ctx.window.axonWorkspaceRunsMixin(),
              ctx.window.axonChatMixin(),
            );

            app.currentResearchPack = () => ({ resources: [{ id: 12, title: 'Acceptance checklist' }] });
            app.mergeUniqueResources = (items) => items;
            app.resolveChatMode = () => 'chat';
            app.usesOllamaBackend = () => false;
            app.rememberComposerHistory = (message) => {
              app.history = [...(app.history || []), message];
            };
            app.resetChatComposerHeight = () => {};
            app.scrollChat = () => {};
            app.setAgentStage = (stage) => { app.stage = stage; };
            app.beginLiveOperator = () => {};
            app.updateLiveOperator = () => {};
            app.clearLiveOperator = () => {};
            app.showToast = (message) => { app.toast = message; };
            app.createAssistantPlaceholder = (respId, mode, retryResources = []) => ({
              id: respId,
              role: 'assistant',
              content: '',
              streaming: true,
              mode,
              retryResources,
            });
            app.uploadImageAttachments = async (options = {}) => {
              app.uploadOptions = {
                workspaceId: options.workspaceId,
                attachmentNames: (options.attachments || []).map((item) => item.name),
              };
              return [{ id: 77, title: 'mobile', kind: 'image' }];
            };
            app.clearImageAttachments = () => {
              app.imageAttachments = [];
              app.imagesCleared = true;
            };
            app.streamChatMessage = async (message, mode, respId, resourceIds, extraPayload, workspaceId) => {
              app.streamPayload = { message, mode, respId, resourceIds, extraPayload, workspaceId };
            };

            await app.sendChat();

            console.log(JSON.stringify({
              history: app.history || [],
              uploadOptions: app.uploadOptions || {},
              imagesCleared: app.imagesCleared === true,
              imageCount: (app.imageAttachments || []).length,
              selectedResourcesCount: (app.selectedResources || []).length,
              streamPayload: app.streamPayload || null,
              userResources: (app.chatMessages[0]?.resources || []).map((item) => Number(item.id)),
              userImageCount: (app.chatMessages[0]?.imageAttachments || []).length,
              chatInput: app.chatInput,
              toast: app.toast || '',
            }));
            """,
        )

        self.assertEqual(payload["history"], ["Review this mobile screenshot"])
        self.assertEqual(payload["uploadOptions"]["workspaceId"], "7")
        self.assertEqual(payload["uploadOptions"]["attachmentNames"], ["mobile.png"])
        self.assertTrue(payload["imagesCleared"])
        self.assertEqual(payload["imageCount"], 0)
        self.assertEqual(payload["selectedResourcesCount"], 0)
        self.assertEqual(payload["streamPayload"]["resourceIds"], [12, 15, 77])
        self.assertEqual(payload["streamPayload"]["workspaceId"], "7")
        self.assertEqual(payload["userResources"], [12, 15, 77])
        self.assertEqual(payload["userImageCount"], 1)
        self.assertEqual(payload["chatInput"], "")
        self.assertEqual(payload["toast"], "")

    def test_upload_image_attachments_targets_resource_upload_endpoint(self):
        payload = _run_script(
            [IMAGE_VIEWER_JS],
            """
            const mixin = ctx.window.axonImageViewerMixin();
            const file = new Blob(['pixel'], { type: 'image/png' });
            file.name = 'capture.png';
            const app = {
              chatProjectId: '42',
              authHeaders() { return { authorization: 'Bearer test-token' }; },
            };
            Object.assign(app, mixin);
            app.imageAttachments = [
              { id: 'img-1', name: 'capture.png', size: 5, dataUrl: 'data:image/png;base64,abc', file },
            ];

            const request = {};
            ctx.fetch = async (url, init = {}) => {
              request.url = url;
              request.method = init.method || 'GET';
              request.auth = init.headers?.authorization || '';
              request.workspaceId = init.body?.get?.('workspace_id') || '';
              request.fileCount = init.body?.getAll?.('files')?.length || 0;
              return {
                ok: true,
                status: 200,
                async json() {
                  return {
                    items: [{ id: 91, title: 'capture', kind: 'image' }],
                  };
                },
              };
            };

            const uploaded = await app.uploadImageAttachments();
            console.log(JSON.stringify({
              request,
              uploaded,
            }));
            """,
        )

        self.assertEqual(payload["request"]["url"], "/api/resources/upload")
        self.assertEqual(payload["request"]["method"], "POST")
        self.assertEqual(payload["request"]["auth"], "Bearer test-token")
        self.assertEqual(payload["request"]["workspaceId"], "42")
        self.assertEqual(payload["request"]["fileCount"], 1)
        self.assertEqual(payload["uploaded"][0]["id"], 91)
        self.assertEqual(payload["uploaded"][0]["kind"], "image")
        self.assertEqual(payload["uploaded"][0]["name"], "capture.png")
        self.assertEqual(payload["uploaded"][0]["dataUrl"], "data:image/png;base64,abc")


if __name__ == "__main__":
    unittest.main()
