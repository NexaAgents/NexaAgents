import asyncio
import sys


async def ainput(prompt: str) -> str:
    """
    Async alternative to input()
    Args:
        prompt (str): Prompt for user input.

    Returns: The stdin str.

    """
    await asyncio.get_event_loop().run_in_executor(None, lambda s=prompt: sys.stdout.write(s + " "))
    user_input: str = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
    return user_input.strip()
