import asyncio
from github.v1.repository_rsm import (
    Repository,
    AttachRequest,
    AttachResponse,
)
from resemble.aio.applications import Application
from resemble.aio.contexts import (
    ReaderContext,
    TransactionContext,
    WriterContext,
)


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


async def main():
    await Application(
        servicers=[RepositoryServicer]
    ).run()


if __name__ == '__main__':
    asyncio.run(main())
