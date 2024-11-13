# https://gist.github.com/Soheab/f46fee27498aad4a8962d59b6f0415c6

from __future__ import annotations
from typing import Any, Callable, Coroutine, Generic, Optional, Union, TYPE_CHECKING


from discord import Interaction, TextStyle
from discord.ui import Modal, TextInput
from discord.utils import maybe_coroutine

if TYPE_CHECKING:
    from typing_extensions import Self


if TYPE_CHECKING:
    from typing_extensions import TypeVar

    ValueT = TypeVar(
        "ValueT", Union[int, str, float, bool], int, str, float, bool, default=str
    )
else:
    from typing import TypeVar

    ValueT = TypeVar("ValueT", Union[int, str, float, bool], int, str, float, bool)


class SimpleModalWaitFor(Modal, Generic[ValueT]):
    def __init__(
        self,
        title: str = "Waiting For Input",
        *,
        check: Optional[
            Callable[[Self, Interaction], Union[Coroutine[Any, Any, bool], bool]]
        ] = None,
        timeout: float = 30.0,
        input_label: str = "Input text",
        input_max_length: int = 100,
        input_min_length: int = 5,
        input_style: TextStyle = TextStyle.short,
        input_placeholder: Optional[str] = None,
        input_default: Optional[str] = None,
        forced_type: Optional[type[ValueT]] = None,
    ):
        super().__init__(title=title, timeout=timeout, custom_id="wait_for_modal")
        self._check: Optional[
            Callable[[Self, Interaction], Union[Coroutine[Any, Any, bool], bool]]
        ] = check
        self.value: Optional[ValueT] = None
        self.interaction: Optional[Interaction] = None

        self.forced_type: Optional[type[ValueT]] = forced_type

        self.answer = TextInput(
            label=input_label,
            placeholder=input_placeholder,
            max_length=input_max_length,
            min_length=input_min_length,
            style=input_style,
            default=input_default,
            custom_id=self.custom_id + "_input_field",
        )
        self.add_item(self.answer)

    def _cast_input(self, value: str) -> ValueT:
        if self.forced_type is None:
            return str(value)  # type: ignore

        valid_bools = {
            "t": True,
            "true": True,
            "y": True,
            "yes": True,
            "1": True,
            "false": False,
            "f": False,
            "n": False,
            "no": False,
            "0": False,
        }

        try:
            if self.forced_type is int:
                return int(value)  # type: ignore
            elif self.forced_type is float:
                return float(value)  # type: ignore
            elif self.forced_type is bool:
                return valid_bools[value.lower()]  # type: ignore
            else:
                return str(value)  # type: ignore
        except (ValueError, KeyError):
            return value  # type: ignore

    async def interaction_check(self, interaction: Interaction) -> bool:
        if self._check:
            return await maybe_coroutine(self._check, self, interaction)

        return True

    async def on_submit(self, interaction: Interaction) -> None:
        self.value = self._cast_input(self.answer.value)
        self.interaction = interaction
        self.stop()
