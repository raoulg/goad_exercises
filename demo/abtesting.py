import requests
import json
import pandas as pd
from pathlib import Path
from tabulate import tabulate
from loguru import logger
from pydantic import BaseModel
import random


class Config(BaseModel):
    ROOT_URL: str = "http://145.38.193.71"
    CACHE_DIR: Path = Path(".cache")
    DATA_DIR: Path = Path("data")
    EMAIL_CACHE_FILE: Path = CACHE_DIR / "email.json"
    RESULTS_FILE: Path = DATA_DIR / "result" / "campaign_results.csv"


class CampaignResult(BaseModel):
    """Pydantic model for successful campaign result"""

    strategy: int
    opened: int
    timestamp: str
    timezone: str


class RateLimitError(BaseModel):
    """Pydantic model for rate limit error response"""

    detail: str


class QueryAPI:
    """Handles API communication with the campaign server."""

    def __init__(self, config: Config):
        self.root_url = config.ROOT_URL
        self.CACHE_DIR = config.CACHE_DIR
        self.email_cache_file = config.EMAIL_CACHE_FILE
        self.email = self._get_email()

    def _get_email(self):
        """Get email from cached file or user input"""
        # Try to load from cache
        cached_email = self._load_cached_email()
        if cached_email:
            return cached_email

        # Ask user for email and cache it
        user_email = input("Please enter your email address: ")
        if not user_email or "@" not in user_email:
            raise ValueError("Invalid email address. Please provide a valid email.")

        self._cache_email(user_email)
        return user_email

    def _load_cached_email(self):
        """Load email from cache file if it exists"""
        try:
            if self.email_cache_file.exists():
                with self.email_cache_file.open("r") as f:
                    data = json.load(f)
                    return data.get("email")
        except Exception as e:
            logger.error(f"Error loading cached email: {e}")
        return None

    def _cache_email(self, email):
        """Save email to cache file"""
        try:
            # Create directory if it doesn't exist
            self.CACHE_DIR.mkdir(exist_ok=True)
            with self.email_cache_file.open("w") as f:
                json.dump({"email": email}, f)
        except Exception as e:
            logger.error(f"Error caching email: {e}")

    def get(self, path, email=None):
        """Generic GET request to the API"""
        url = f"{self.root_url}/{path}"

        if email:
            url += f"?email={email}"

        response = requests.get(url)
        return response.json()

    def get_campaign(self, strategy):
        """Get campaign results for a specific strategy, handling potential rate limit errors"""
        path = f"campaign/{strategy}"
        email = self.email
        response_data = self.get(path, email)

        # Check if this is a rate limit error
        if "detail" in response_data:
            return (False, RateLimitError(detail=response_data["detail"]))

        # Try to parse as a campaign result
        try:
            result = CampaignResult(**response_data)
            return (True, result)  # Success tuple
        except Exception as e:
            logger.error(f"Error parsing campaign result: {e}")
            return (False, response_data)  # General error tuple

    def get_remaining(self):
        """Get remaining campaign trials"""
        path = "remaining"
        email = self.email
        return self.get(path, email)

    def get_leaderboard(self):
        """Get the current leaderboard"""
        path = "leaderboard"
        return self.get(path, email=None)

    def formatted_leaderboard(self):
        """Get nicely formatted leaderboards for both success ratio and total requests"""
        leaderboard_data = self.get_leaderboard()
        if not leaderboard_data:
            return "No leaderboard data available."

        result = []

        # Format the success ratio leaderboard
        if (
            "top_by_success_ratio" in leaderboard_data
            and leaderboard_data["top_by_success_ratio"]
        ):
            result.append("Top Users by Success Ratio:")
            headers = ["Rank", "Email", "Success Rate", "Successful", "Total Requests"]
            table_data = []

            for i, entry in enumerate(leaderboard_data["top_by_success_ratio"], 1):
                email = entry.get("email", "Unknown")
                table_data.append(
                    [
                        i,  # Rank
                        email,
                        f"{entry.get('success_rate', 0):.2%}",  # Format as percentage
                        entry.get("successful_requests", 0),
                        entry.get("total_requests", 0),
                    ]
                )

            result.append(tabulate(table_data, headers, tablefmt="grid"))

        # Add a spacer between tables if both exist
        if (
            result
            and "top_by_total_requests" in leaderboard_data
            and leaderboard_data["top_by_total_requests"]
        ):
            result.append("")  # Empty line as separator

        # Format the total requests leaderboard
        if (
            "top_by_total_requests" in leaderboard_data
            and leaderboard_data["top_by_total_requests"]
        ):
            result.append("Top Users by Total Requests:")
            headers = ["Rank", "Email", "Total Requests", "Successful", "Success Rate"]
            table_data = []

            for i, entry in enumerate(leaderboard_data["top_by_total_requests"], 1):
                email = entry.get("email", "Unknown")
                table_data.append(
                    [
                        i,  # Rank
                        email,
                        entry.get("total_requests", 0),
                        entry.get("successful_requests", 0),
                        f"{entry.get('success_rate', 0):.2%}",  # Format as percentage
                    ]
                )

            result.append(tabulate(table_data, headers, tablefmt="grid"))

        # Join all parts with newlines
        return "\n".join(result)


class FileHandler:
    """Handles storing and loading campaign results."""

    def __init__(self, config: Config):
        config.DATA_DIR.mkdir(exist_ok=True, parents=True)
        self.results_file = config.RESULTS_FILE

        # Create results file with headers if it doesn't exist
        if not self.results_file.exists():
            self._create_results_file()

    def _create_results_file(self):
        """Create the results CSV file with headers"""
        headers = ["strategy", "opened", "timestamp", "timezone"]
        pd.DataFrame(columns=headers).to_csv(self.results_file, index=False)  # type: ignore

    def store_result(self, result):
        """Store a campaign result in the CSV file"""
        # Convert result to a DataFrame row
        df_row = pd.DataFrame([result.model_dump()])

        # Append to CSV without writing headers again
        df_row.to_csv(self.results_file, mode="a", header=False, index=False)
        logger.success(f"Stored result to {self.results_file}")
        return result

    def load_results(self):
        """Load all stored results as a pandas DataFrame"""
        if not self.results_file.exists():
            return pd.DataFrame()

        # Read CSV and parse timestamp column
        df = pd.read_csv(self.results_file)
        if not df.empty and "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        return df


class CampaignManager:
    """High-level class to manage campaign operations."""

    def __init__(self, config: Config):
        self.query_api = QueryAPI(config)
        self.file_handler = FileHandler(config)

    def evaluate_strategy(self, strategy):
        """Evaluate a specific strategy and return the result (0 or 1) or None if rate limited"""
        # Get campaign result for the strategy
        success, data = self.query_api.get_campaign(strategy)

        if not success:
            # Check if it's a rate limit error
            if isinstance(data, RateLimitError):
                logger.warning(f"Rate limit exceeded: {data.detail}")
                return None
            else:
                logger.error(f"API error: {data}")
                return None

        # Store the result if successful
        if not isinstance(data, CampaignResult):
            logger.error(f"Unexpected data format: {data}")
            return None
        self.file_handler.store_result(data)

        # Return opened value (0 or 1)
        return data.opened

    def get_results_dataframe(self):
        """Get all stored results as a DataFrame"""
        return self.file_handler.load_results()


if __name__ == "__main__":
    # Configure logger
    logger.add("logs/campaign_api.log", rotation="10 MB")
    config = Config()

    # Initialize campaign manager
    campaign_manager = CampaignManager(config)

    # Try a strategy
    result = None
    for i in range(5):
        strategy = random.randint(0, 3)
        result = campaign_manager.evaluate_strategy(strategy)
        if result is not None:
            print(
                f"Strategy {strategy} result: {'Opened' if result == 1 else 'Not Opened'}"
            )
        else:
            print(
                f"Unable to evaluate strategy {strategy} due to rate limiting or other error"
            )

    # Get remaining attempts
    remaining = campaign_manager.query_api.get_remaining()
    print(f"Remaining attempts: {remaining}")

    # Display leaderboard
    print("\nLeaderboard:")
    print(campaign_manager.query_api.formatted_leaderboard())
