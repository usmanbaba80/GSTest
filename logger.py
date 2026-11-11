import logging
import sys
from typing import Optional
from config import settings

def setup_logging(log_level: Optional[str] = None) -> logging.Logger:
    """
    Setup structured logging for the application.
    
    Args:
        log_level: Optional log level override
        
    Returns:
        Configured logger instance
    """
    level = log_level or settings.log_level
    
    # Create formatter
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    root_logger.addHandler(handler)
    
    # Create application logger
    logger = logging.getLogger('gs_backend')
    logger.setLevel(getattr(logging, level.upper()))
    
    return logger

# Global logger instance
logger = setup_logging() 