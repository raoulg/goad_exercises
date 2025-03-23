from goad_toolkit.config import DataConfig, FileConfig
from goad_toolkit.dataprocessor import CovidDataProcessor
from goad_toolkit.models import linear_model, mse, train_model
from goad_toolkit.analytics import DistributionFitter
from loguru import logger
from goad_toolkit.visualizer import (
    ComparePlot,
    PlotSettings,
    ResidualPlot,
    PlotFits,
    FitPlotSettings,
)
from pathlib import Path
import pandas as pd
import numpy as np


def preprocess():
    logger.info("Start preprocessing data...")
    data_config = DataConfig()
    file_config = FileConfig()

    covidprocessor = CovidDataProcessor(file_config, data_config)
    processed = covidprocessor.process()
    logger.success("Data processed.")
    return processed


def check_path(filepath: Path):
    parentdir = filepath.parent
    if not parentdir.exists():
        parentdir.mkdir(parents=True)
        logger.info(f"Created directory {parentdir}")


def save_fig(fig, imgpath):
    assert fig is not None, "No figure was created"
    check_path(Path(imgpath))
    fig.savefig(imgpath)
    logger.success(f"Z-Scores saved to {imgpath}")


def viz_zscores(data):
    plotsettings = PlotSettings(
        xlabel="date",
        ylabel="normalized values",
        title="Z-Scores of Deaths and Positive Tests",
    )
    compareplot = ComparePlot(plotsettings)
    fig, _ = compareplot.plot(
        data=data, x="date", y1="deaths_shifted_zscore", y2="positivetests_zscore"
    )
    imgpath = "data/result/zscores.png"
    save_fig(fig, imgpath)


def model(data: "pd.DataFrame") -> "pd.DataFrame":
    X = data["positivetests"].values  # noqa: N806
    y = data["deaths"].values
    assert isinstance(X, np.ndarray)
    assert isinstance(y, np.ndarray)

    initial_params = [0.01, 1.0]
    bounds = [(0, 1.0), (0, None)]
    params = train_model(X, y, linear_model, mse, initial_params, bounds=bounds)
    logger.success(f"Fitted model with parameters: {params}")
    yhat = linear_model(X, params)
    data["Predicted deaths"] = yhat
    data["residual"] = data["deaths_shifted"].values - yhat
    return data


def viz_model(data):
    plotsettings = PlotSettings(xlabel="date", ylabel="deaths", title="Covid-19 data")
    fig, _ = ComparePlot(plotsettings).plot(
        data=data, x="date", y1="deaths_shifted", y2="Predicted deaths"
    )

    imgpath = "data/result/linear_results.png"
    save_fig(fig, imgpath)


def viz_residual(data):
    settings = PlotSettings(
        figsize=(12, 6), title="Residual Plot", xlabel="dates", ylabel="error"
    )
    resplot = ResidualPlot(settings)
    fig, _ = resplot.plot(
        data=data,
        x="date",
        y="residual",
        date="2021-01-06",
        datelabel="Vaccination Started",
        interval=1,
    )
    imgpath = "data/result/residuals.png"
    save_fig(fig, imgpath)


def viz_distribution_fit(data):
    fitter = DistributionFitter()
    fits = fitter.fit(data["residual"], discrete=False)
    best = fitter.best(fits)
    logger.success(f"Best fit: {best}")
    settings = PlotSettings(
        figsize=(12, 6), title="Residuals", xlabel="error", ylabel="probability"
    )
    fitplotsettings = FitPlotSettings(bins=30, max_fits=3)
    fitplotter = PlotFits(settings)
    fig = fitplotter.plot(
        data=data["residual"], fit_results=fits, fitplotsettings=fitplotsettings
    )
    imgpath = "data/result/distribution_fit.png"
    save_fig(fig, imgpath)


def main():
    data = preprocess()
    viz_zscores(data)
    data = model(data)
    viz_model(data)
    viz_residual(data)
    viz_distribution_fit(data)
    logger.success("All done!")


if __name__ == "__main__":
    main()
