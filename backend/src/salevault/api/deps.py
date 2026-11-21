from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from salevault.api.launcher import RunLauncher
from salevault.db.engine import session_scope


def get_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.factory
    return factory


def get_session(
    factory: Annotated[sessionmaker[Session], Depends(get_factory)],
) -> Iterator[Session]:
    with session_scope(factory) as session:
        yield session


def get_launcher(request: Request) -> RunLauncher:
    launcher: RunLauncher = request.app.state.launcher
    return launcher


SessionDep = Annotated[Session, Depends(get_session)]
FactoryDep = Annotated[sessionmaker[Session], Depends(get_factory)]
LauncherDep = Annotated[RunLauncher, Depends(get_launcher)]
