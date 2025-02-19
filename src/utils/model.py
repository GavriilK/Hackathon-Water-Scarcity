import os
import sys
import re
import random
from math import sqrt
from datetime import datetime
from typing import List, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from tabulate import tabulate
import joblib

from sklearn.metrics import mean_squared_error, mean_absolute_error

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..', '..')))

from src.utils.helpers import save_or_create


def standardize_values(y: np.ndarray,
                       stations: np.ndarray,
                       station_stats: pd.DataFrame) -> np.ndarray:
    """
    Standardize values based on station-level statistics.

    Parameters:
        y (np.ndarray): The values to standardize.
        stations (np.ndarray): The station codes.
        station_stats (pd.DataFrame): The station-level statistics.

    Returns:
        np.ndarray: The standardized values.
    """
    out = np.empty_like(y, dtype=float)
    for s in np.unique(stations):
        idx = stations == s
        min = station_stats.loc[s, 'min']
        max = station_stats.loc[s, 'max']
        out[idx] = (y[idx] - min) * 100.0 / (max - min) 
    return out


def split_dataset(
    ds: pd.DataFrame, 
    percentage_split: float = 0.75, 
    split_time: str = None, 
    seed: int = 42,
    test_stations_spatial: np.ndarray = None
):
    """
    Splits the dataset into training and testing sets based on the specified method.

    Parameters:
        ds (pd.DataFrame): The dataset containing data.
        percentage_split (float): The proportion of stations for the training set (default is 0.75).
        split_time (str, optional): The timestamp for temporal split (required if SPLIT is "temporal").
        seed (int): Random seed for reproducibility (default is 42).

    Returns:
        tuple: X_train, y_train, X_test, y_test, train_stations, test_stations
    """
    # Get unique station names and shuffle
    station_code = ds['station_code'].unique()
    # set seed
    random.seed(seed)
    random.shuffle(station_code)

    if test_stations_spatial is not None:
        train_stations_spatial = [s for s in station_code if s not in test_stations_spatial]
    else:
        test_stations_spatial = station_code[int(len(station_code) * percentage_split):]
        train_stations_spatial = station_code[:int(len(station_code) * percentage_split)]

    ds_test_temporal = ds[pd.to_datetime(ds.index) >= pd.to_datetime(split_time)]
    ds_test_temporal = ds_test_temporal[ds_test_temporal['station_code'].isin(train_stations_spatial)]

    ds_train = ds[ds['station_code'].isin(train_stations_spatial)]
    ds_test = ds[ds['station_code'].isin(test_stations_spatial)]
    ds_train = ds_train[pd.to_datetime(ds_train.index) < pd.to_datetime(split_time)]
    ds_test = ds_test[pd.to_datetime(ds_test.index) >= pd.to_datetime(split_time)]
    
    return ds_train, ds_test, ds_test_temporal


def get_station_stats(
    y: np.ndarray, 
    station_code: np.ndarray
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Return station-level statistics (mean, std, min, max).
    """
    df = pd.DataFrame({'y': y, 'station_code': station_code})
    station_stats = df.groupby('station_code')['y'].agg(['mean', 'std', 'min', 'max'])
    return station_stats


def standardize_prediction_intervals(
    y_pred_intervals: np.ndarray, 
    stations: np.ndarray, 
    station_stats: pd.DataFrame
) -> Tuple[np.ndarray, np.ndarray]:
    if y_pred_intervals is None:
        return None, None
    
    if len(y_pred_intervals.shape) == 3:
        y_pred_lower_std = standardize_values(y_pred_intervals[:, 0, 0], stations, station_stats)
        y_pred_upper_std = standardize_values(y_pred_intervals[:, 1, 0], stations, station_stats)
    else:
        y_pred_lower_std = standardize_values(y_pred_intervals[:, 0], stations, station_stats)
        y_pred_upper_std = standardize_values(y_pred_intervals[:, 1], stations, station_stats)

    return y_pred_lower_std, y_pred_upper_std


def compute_per_station_metrics(
    y_true_std: np.ndarray,
    y_pred_std: np.ndarray,
    stations: np.ndarray,
    y_pred_intervals: np.ndarray = None,
    y_pred_lower_std: np.ndarray = None,
    y_pred_upper_std: np.ndarray = None
) -> pd.DataFrame:
    """
    Compute scaled RMSE, scaled MAE, coverage, and scaled interval size 
    for each station. Returns a DataFrame of station-level metrics.
    """
    station_list = np.unique(stations)

    records = []

    has_intervals = (
        (y_pred_intervals is not None) and 
        (y_pred_lower_std is not None) and 
        (y_pred_upper_std is not None)
    )

    for s in station_list:
        idx = (stations == s)
        y_s = y_true_std[idx]
        y_pred_s = y_pred_std[idx]

        rmse_s = sqrt(mean_squared_error(y_s, y_pred_s))
        mae_s = mean_absolute_error(y_s, y_pred_s)

        if has_intervals:
            y_lower_s = y_pred_lower_std[idx]
            y_upper_s = y_pred_upper_std[idx]

            # Estimate sigma using the 95% confidence interval approximation
            sigma_s = (y_upper_s - y_lower_s) / 3.29

            # Compute Gaussian negative log-likelihood
            nll_s = (1 / len(y_s)) * np.sum(
               np.log(sigma_s) + abs((y_s - y_pred_s)) / abs(2 * sigma_s)
            )

            coverage_s = np.mean((y_s >= y_lower_s) & (y_s <= y_upper_s))
            interval_size_s = np.mean(y_upper_s - y_lower_s)
        else:
            sigma_s = np.std(y_s - y_pred_s)  # Fallback estimation
            sigma_s = max(sigma_s, 1e-6)  # Ensure non-zero, positive sigma

            nll_s = (1 / len(y_s)) * np.sum(
                np.log(sigma_s) + abs((y_s - y_pred_s)) / abs(2 * sigma_s)
            )

            coverage_s = np.nan
            interval_size_s = np.nan

        # Collect station-level metrics
        records.append({
            'station_code': s,
            'scaled_rmse': rmse_s,
            'scaled_mae': mae_s,
            'coverage': coverage_s,
            'scaled_interval_size': interval_size_s,
            'log_likelihood': nll_s
        })

    return pd.DataFrame(records)


def summarize_metrics(
    station_metrics_df: pd.DataFrame, 
    model_name: str, 
    dataset_type: str, 
    alpha: float, 
    beta: float
) -> pd.DataFrame:
    """
    Given a station-level metrics DataFrame, compute average (per station) values and a final score.
    Returns a single-row DataFrame containing the summary metrics for the model.
    """
    rmse_final = np.nanmean(station_metrics_df['scaled_rmse'])
    mae_final = np.nanmean(station_metrics_df['scaled_mae'])
    log_likelihood = np.nanmean(station_metrics_df['log_likelihood'])
    
    if station_metrics_df['coverage'].count() == 0:
        coverage_final = np.nan
        interval_size_final = np.nan
    else:
        coverage_final = np.nanmean(station_metrics_df['coverage'])
        interval_size_final = np.nanmean(station_metrics_df['scaled_interval_size'])
    score = alpha * rmse_final + beta * interval_size_final

    data = {
        "model": [model_name],
        "dataset": [dataset_type],
        "scaled_rmse": [rmse_final],
        "log_likelihood": [log_likelihood],
        "scaled_mae": [mae_final],
        "coverage": [coverage_final],
        "scaled_interval_size": [interval_size_final],
        "final_score": [score]
    }
    return pd.DataFrame(data)


def print_summary_table(
    summary_df: pd.DataFrame
):
    """
    Print a summary of the model-level metrics using tabulate.
    """
    row = summary_df.iloc[0]
    table_data = [
        ["Model", row["model"]],
        ["Dataset Type", row["dataset"]],
        ["Average Scaled RMSE", row["scaled_rmse"]],
        ["Average Scaled MAE", row["scaled_mae"]],
        ["Average Coverage", row["coverage"]],
        ["Average Scaled Interval Size", row["scaled_interval_size"]],
        ["Final Score", row["final_score"]],
    ]
    print("\n" + tabulate(table_data, headers=["Metric", "Value"], tablefmt="pretty") + "\n")


def generate_boxplots(
    station_metrics_df: pd.DataFrame, 
    column_to_display: str, 
    prefix: str,
    title: str,
    save: bool = False,
    display: bool = True
):
    """
    Generate and save boxplots based on the station-level metrics.
    If RMSE_mode is True, only shows a scaled RMSE boxplot.
    Otherwise, shows coverage & interval size boxplots.
    """
    fig1, ax1 = plt.subplots(figsize=(10, 4))
    station_metrics_df.boxplot(column=column_to_display, by='model', ax=ax1)
    ax1.set_title("Per-Station Scaled Gaussian Log-Likelihood")
    ax1.set_xlabel("Model")
    ax1.set_ylabel("Scaled GLL")
    ax1.set_ylim(0, 5)
    fig1.suptitle(title)
    plt.tight_layout()
    if display:
        plt.show()

    if save:
        current_date = pd.Timestamp.now().strftime('%d-%m-%Y_%H-%M')
        save_path = f'../../figures/models/{prefix}_{current_date}_boxplots.png'
        save_or_create(plt, save_path)


def compare_models_per_station(
    y: np.ndarray,
    predictions: List[dict],
    station_code: np.ndarray,
    prefix: str = "",
    column_to_display: str = True,
    title: str = "Model Evaluation",
    save: bool = False,
    display: bool = True
):
    """
    Evaluate the performance of one or multiple models at the station level. 

    This function calculates scaled RMSE, scaled MAE, coverage, 
    and scaled interval size for each station and then averages them across stations. 
    It also generates boxplots of per-station metrics (scaled RMSE or coverage/interval size) 
    and saves the figure.

    Parameters
    ----------
    y : np.ndarray
        Ground truth values for the test set.
    predictions : List[dict]
        A list of prediction dictionaries. Each dictionary must include:
          - "model": A string with the model name.
          - "dataset": Either "train" or "test".
          - "prediction": A 1D array of predicted values.
          - "prediction_interval" (optional): A 2D or 3D array of interval bounds.
    station_code : np.ndarray
        An array of station identifiers corresponding to each entry in y.
    prefix : str, optional
        A string prefix for saving figures.
    column_to_display : str, optional
        The column to display in the boxplots.
    title : str, optional
        The title of the boxplots.
    save : bool, optional
        If True, the boxplots are saved.
    display : bool, optional
        If True, the boxplots are displayed.
    """
    all_station_metrics = []

    for pred in predictions:
        model_name = pred["model"]

        station_stats = get_station_stats(y, station_code)

        y_pred = pred["prediction"]
        y_pred_intervals = pred.get("prediction_interval", None)

        y_true_std = standardize_values(y, station_code, station_stats)
        y_pred_std = standardize_values(y_pred, station_code, station_stats)

        y_pred_lower_std, y_pred_upper_std = standardize_prediction_intervals(
            y_pred_intervals, station_code, station_stats
        )

        station_metrics_df = compute_per_station_metrics(
            y_true_std=y_true_std,
            y_pred_std=y_pred_std,
            stations=station_code,
            y_pred_intervals=y_pred_intervals,
            y_pred_lower_std=y_pred_lower_std,
            y_pred_upper_std=y_pred_upper_std
        )

        station_metrics_df["model"] = model_name
        all_station_metrics.append(station_metrics_df)

    station_metrics_df = pd.concat(all_station_metrics, ignore_index=True)

    generate_boxplots(station_metrics_df,
                      column_to_display,
                      prefix,
                      title,
                      save,
                      display)


def load_models_auto(
    model_name: str,
    model_dir: str = "../../models/"
) -> List[any]:
    """
    Auto-load the latest models
    for week0, week1, and week2 from the specified directory.

    Parameters:
    - model_name (str): The base model name to search for (e.g., "mapie_quantile").
    - model_dir (str): Directory where models are stored.

    Returns:
    - List of loaded models in the order [week0, week1, week2].
    """

    pattern_str = rf"^{model_name}_(\d{{4}}-\d{{2}}-\d{{2}}_\d{{2}}-\d{{2}}-\d{{2}})_week_([0-9]).pkl$"
    pattern = re.compile(pattern_str)
    latest_paths = {}

    for fname in os.listdir(model_dir):
        match = pattern.match(fname)
        if match:
            date_str, week_str = match.groups()
            week_num = int(week_str)
            date_obj = datetime.strptime(date_str, "%Y-%m-%d_%H-%M-%S")            
            if week_num not in latest_paths:
                latest_paths[week_num] = (date_obj, fname)
            else:
                current_latest_date, _ = latest_paths[week_num]
                if date_obj > current_latest_date:
                    latest_paths[week_num] = (date_obj, fname)

    loaded_mapie = []
    for i in [0, 1, 2, 3]:
        if i not in latest_paths:
            raise ValueError(f"No mapie_quantile model found for week{i} in {model_dir}.")
        model_file = latest_paths[i][1]
        full_path = os.path.join(model_dir, model_file)
        loaded_mapie.append(joblib.load(full_path))

    return loaded_mapie


def average_ebms(
        ebm_list
    ):
    """
    Takes a list of trained EBM models and returns a single EBM
    whose intercept and shape functions (term_scores_) are averaged.
    """
    # 1) Make a deep copy of the first EBM to use as a "template"
    avg_ebm = copy.deepcopy(ebm_list[0])
    
    # 2) Average the intercepts
    intercepts = [ebm.intercept_ for ebm in ebm_list]
    avg_ebm.intercept_ = np.mean(intercepts, axis=0)

    # 3) Average the term scores
    for i in range(len(avg_ebm.term_scores_)):
        scores_i = [ebm.term_scores_[i] for ebm in ebm_list]
        avg_ebm.term_scores_[i] = np.mean(scores_i, axis=0)

    return avg_ebm