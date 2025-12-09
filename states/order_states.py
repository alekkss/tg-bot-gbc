from aiogram.fsm.state import State, StatesGroup


class OrderStates(StatesGroup):
    """Состояния для работы с заказами"""
    waiting_for_order_number = State()
