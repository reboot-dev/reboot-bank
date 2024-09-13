import asyncio
import grpc
import http.client
import json
import os
import sys
from github.v1 import repository_pb2_grpc
from github.v1.repository_rsm import (
    Repository,
    AttachRequest,
    AttachResponse,
    WebhookRequest,
)
from google.api.httpbody_pb2 import HttpBody
from resemble.aio.applications import Application
from resemble.aio.contexts import (
    ReaderContext,
    TransactionContext,
    WriterContext,
)

if "GITHUB_WEBHOOK_TOKEN" not in os.environ:
    print("Expected GITHUB_WEBHOOK_TOKEN env var is missing", file=sys.stderr)
    sys.exit(1)

GITHUB_WEBHOOK_TOKEN = os.environ["GITHUB_WEBHOOK_TOKEN"]
CODESPACE_NAME = os.environ["CODESPACE_NAME"]
WEBHOOK_URL = f"https://{CODESPACE_NAME}-9991.app.github.dev/github/v1/repository/webhook"

OWNER = 'benh'
REPO = 'resemble-hello'


class RepositoryServicer(Repository.Interface):

    async def Attach(
        self,
        context: WriterContext,
        state: Repository.State,
        request: AttachRequest,
    ) -> AttachResponse:
        state.org = request.org
        state.repo = request.repo
        return AttachResponse()


class HttpServicer(repository_pb2_grpc.HttpServicer):

    async def Webhook(
        self,
        request: WebhookRequest,
        grpc_context: grpc.aio.ServicerContext,
    ) -> HttpBody:

        headers = grpc_context.invocation_metadata()

        # Print headers and JSON body.
        print("\nReceived Webhook:")
        print("Headers:")
        for key, value in headers:
            print(f"{key}: {value}")

        print("\nBody:")
        try:
            json_body = json.loads(request.data)
            print(json.dumps(json_body, indent=4))
        except json.JSONDecodeError:
            print("Received non-JSON body.")
            print(request.data)

        # Send 200 OK response.
        return HttpBody()


def register_webhook():

    conn = http.client.HTTPSConnection("api.github.com")
    headers = {
        "Authorization": f"token {GITHUB_WEBHOOK_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Python-HttpClient"  # GitHub API requires a User-Agent header
    }
    payload = {
        "name": "web",
        "active": True,
        "events": ["*"],  # Listen to all events
        "config": {
            "url": WEBHOOK_URL,
            "content_type": "json"
        }
    }

    conn.request("POST", f"/repos/{OWNER}/{REPO}/hooks", body=json.dumps(payload), headers=headers)
    response = conn.getresponse()
    response_data = response.read().decode()

    if response.status == 201:
        print("Webhook successfully created!")
    else:
        print(f"Failed to create webhook: {response.status} - {response_data}")


async def initialize(context):
    register_webhook()


async def main():
    await Application(
        servicers=[RepositoryServicer],
        legacy_grpc_servicers=[HttpServicer],
        initialize=initialize,
    ).run()


if __name__ == '__main__':
    asyncio.run(main())
