import logging
logger = logging.getLogger(__name__)

def local_fix(code: str) -> str:
    try:
        import autopep8
        return autopep8.fix_code(code, options={"aggressive": 1, "max_line_length": 99})
    except ImportError:
        logger.warning('"autopep8 not installed"')
        return code
    except Exception as exc:
        logger.error('"autopep8 failed: %s"', exc)
        return code
