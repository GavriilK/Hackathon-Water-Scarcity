import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import MonthLocator, DateFormatter
import itertools
from cartopy import crs as ccrs
from cartopy import feature as cfeature

def plot_water_flows(
        train: pd.DataFrame,
        test_spatio: pd.DataFrame = None,
        test_spatio_tempo: pd.DataFrame = None,
        max_stations: int = 50,
        display: bool = True,
        save: bool = False
    ) -> None:
    """
    Plots the water flow for training and (optionally) testing datasets for each station.

    Args:
        dataset_baseline_train (pd.DataFrame): Training dataset with water flow data.
        dataset_baseline_test (pd.DataFrame, optional): Testing dataset with water flow data.
            If not provided, only the training data will be plotted.
        max_stations (int): Maximum number of stations to plot (default: 50).
        display (bool): Whether to display the plot (default: True).
        save (bool): Whether to save the plot as a PNG file (default: False).

    Returns:
        None. Displays or saves the generated plot.
    """
    # Prepare training data and, if available, testing data
    train = train.reset_index().rename(columns={"water_flow_week1": "water_flow_train"})
    if test_spatio is not None:
        test_spatio = test_spatio.reset_index().rename(columns={"water_flow_week1": "water_flow_ts"})
    if test_spatio_tempo is not None:
        test_spatio_tempo = test_spatio_tempo.reset_index().rename(columns={"water_flow_week1": "water_flow_tst"})
    
    data = pd.concat([train,
                      test_spatio,
                      test_spatio_tempo], ignore_index=False)


    # Convert the ObsDate column to datetime
    data['ObsDate'] = pd.to_datetime(data['ObsDate'])
    
    # Group data by station code and only process the first max_stations groups
    station_groups = itertools.islice(data.groupby('station_code', sort=False), max_stations)
    groups_list = list(station_groups)
    nb_fig = len(groups_list)
    
    # Create subplots for each station
    fig, axes = plt.subplots(nb_fig, 1, figsize=(20, 5 * nb_fig), sharex=True)
    if nb_fig == 1:
        axes = [axes]
    
    for ax, (station_code, station_data) in zip(axes, groups_list):
        # Plot training data
        ax.plot(station_data['ObsDate'], station_data['water_flow_train'],
                label='Training', color='blue')
        # Plot testing data if available
        if test_spatio is not None:
            ax.plot(station_data['ObsDate'], station_data['water_flow_ts'],
                    label='Temporal Split', color='orange')
        if test_spatio_tempo is not None:
            ax.plot(station_data['ObsDate'], station_data['water_flow_tst'],
                    label='Spatio-temporal Split', color='red')
        ax.set_title(f'Water Flow for Station: {station_code}')
        ax.set_xlabel('Observation Date')
        ax.set_ylabel('Average weekly water Flow (m³/s)')
        ax.legend()
        ax.grid(True)
        
        # Set x-axis ticks to display every 3 months and format the dates
        ax.xaxis.set_major_locator(MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(DateFormatter('%b %Y'))
    
    plt.xticks(rotation=45)
    plt.tight_layout()

    if save:
        current_date = pd.Timestamp.now().strftime('%d-%m-%Y_%H-%M')
        save_path = f'../../figures/data/{current_date}_wf_stations.png'
        fig.savefig(save_path)
        print(f"Plot saved to {save_path}")

    if display:
        plt.show()
    else:
        plt.close(fig)


def plot_hydrographic_maps(
        area: str,
        gdf_dict: dict,
        bbox: dict
    ) -> None:
    """
    Plots four hydrographic maps for a given area.
    
    Parameters:
        area (str): The area to plot.
        gdf_dict (dict): Dictionary containing GeoDataFrames with keys "region", "sector", "sub_sector", "zone".
        bbox (dict): Dictionary containing bounding box coordinates for each area.
    """
    fig, axes = plt.subplots(1, 4, figsize=(15, 4), subplot_kw={'projection': ccrs.PlateCarree()})
    fig.suptitle(f"{area} Hydrographic Division - 4 Levels", fontsize=16)
    BBOX_DISPLAY = [bbox[area][0], bbox[area][2], bbox[area][1], bbox[area][3]]
    
    titles = [
        "Hydrographic Region (1st Order)",
        "Hydrographic Sector (2nd Order)",
        "Hydrographic Sub-Sector (3rd Order)",
        "Hydrographic Zone (4th Order)"
    ]
    colors = ["lightblue", "lightgreen", "khaki", "salmon"]
    
    for i, (key, color) in enumerate(zip(["region", "sector", "sub_sector", "zone"], colors)):
        gdf_dict[key][area].plot(ax=axes[i], color=color, edgecolor="black")
        axes[i].set_title(titles[i])
        axes[i].axis("off")
        axes[i].set_extent(BBOX_DISPLAY, crs=ccrs.PlateCarree())
        axes[i].add_feature(cfeature.BORDERS, linestyle=':', edgecolor='black', linewidth=1, zorder=7)
        axes[i].add_feature(cfeature.COASTLINE, linewidth=0.8, zorder=7)
        axes[i].add_feature(cfeature.LAKES, facecolor='lightblue', zorder=7)
        axes[i].add_feature(cfeature.OCEAN, facecolor='lightblue', zorder=7)
    
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()