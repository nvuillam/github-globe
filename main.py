import os
import time

import staticmaps
from geojson import Point, Feature, dumps, FeatureCollection, loads
from geopy import TomTom
from geopy.exc import GeopyError
from github import Github, RateLimitExceededException
from github_dependents_info import GithubDependentsInfo


def collect(gh_token: str, geo_token: str, user: str, additional_repos: str):
    geo_locations = {}
    user_locations = {}

    if os.path.exists("global_usage.json"):
        with open("global_usage.json", 'r') as data_file:
            features = FeatureCollection(loads(data_file.read())).get("features")
            if features is not None:
                for feature in features.features:
                    properties = feature.get("properties")
                    if properties is not None:
                        name = properties.get("name")
                        location = properties.get("location")
                        if name is not None and location is not None:
                            user_locations[name] = location
                            geo = feature.get("geometry")
                            if geo is not None:
                                coordinates = geo.get("coordinates")
                                if len(coordinates) == 2:
                                    geo_locations[location] = Point((coordinates[0], coordinates[1]))

    gh = Github(login_or_token=gh_token)
    nn = TomTom(api_key=geo_token)
    base_user = get_user(gh, user)
    repos = get_repos(gh, base_user)

    if additional_repos is not None:
        for repo in additional_repos.split(","):
            additional_repo = {
                "full_name": repo,
                "name": repo.split("/")[1]
            }
            repos.append(additional_repo)

    location_details = set()

    for repo in repos:
        print("checking: " + repo["name"])
        gh_deps_info = GithubDependentsInfo(repo["full_name"])
        gh_deps_info.collect()
        for package in gh_deps_info.packages:
            # Handle dependent package owner user
            for dependent in package["public_dependents"]:
                user_name = dependent["name"].split("/")[0]
                handle_user_location(geo_locations, user_locations, gh, nn, location_details, user_name)
                # Handle dependent package stargazers
                for stargazer in repo["stargazers"]:
                    handle_user_location(geo_locations, user_locations, gh, nn, location_details, stargazer.login)

    features = []
    for usage in location_details:
        p = Point((usage.longitude, usage.latitude))
        features.append(Feature(geometry=p, properties={
            "name": usage.name,
            "location": usage.location,
        }))

    with open("global_usage.json", 'w') as data_file:
        data_file.write(dumps(FeatureCollection(features)))

def handle_user_location(geo_locations, user_locations, gh, nn, location_details, user_name):
    location = ""
    if user_name in user_locations:
        location = user_locations[user_name]
    else:
        repo_user = get_user(gh, user_name)
        if repo_user.location is not None:
            location = repo_user.location
    if location:
        if any(c.isalpha() for c in location):
            if location not in geo_locations:
                try:
                    geo_locations[location] = nn.geocode(location)
                except GeopyError:
                    print("ignoring:" + location)
            if location in geo_locations and geo_locations[location] is not None:
                geo_location = geo_locations[location]
                if hasattr(geo_location, 'latitude') and hasattr(geo_location, 'longitude'):
                    u = Usage(user_name, location, geo_location.latitude, geo_location.longitude)
                    location_details.add(u)


def create_map():
    context = staticmaps.Context()
    context.set_tile_provider(staticmaps.tile_provider_OSM)

    if os.path.exists("global_usage.json"):
        with open("global_usage.json") as data_file:
            features = FeatureCollection(loads(data_file.read())).get("features")
            if features is not None:
                for feature in features.features:
                    geo = feature.get("geometry")
                    if geo is not None:
                        coordinates = geo.get("coordinates")
                        if len(coordinates) == 2:
                            loc = staticmaps.create_latlng(coordinates[1], coordinates[0])
                            context.add_object(staticmaps.Marker(loc, color=staticmaps.GREEN, size=4))

        svg_image = context.render_svg(2048, 1024)
        with open("global_usage.svg", "w", encoding="utf-8") as f:
            svg_image.write(f, pretty=True)


def get_repos(gh, base_user):
    try:
        repos = base_user.get_repos()
        repos_dicts = []
        for repo in repos:
            repo_dict = {
                "full_name": repo.full_name,
                "name": repo.name,
                "stargazers": get_repo_stargazers(gh, repo)
            }
            repos_dicts.append(repo_dict)
        return repos_dicts
    except RateLimitExceededException as e:
        handle_rate_limit(e)
        return get_repos(gh, base_user)


def get_user(gh, user):
    try:
        return gh.get_user(user)
    except RateLimitExceededException as e:
        handle_rate_limit(e)
        return get_user(gh, user)

def get_repo_stargazers(gh, repo):
    try:
        return repo.get_stargazers()
    except RateLimitExceededException as e:
        handle_rate_limit(e)
        return get_repo_stargazers(gh, repo)


class Usage:
    def __init__(self, name, location, latitude, longitude):
        self.name = name
        self.location = location
        self.latitude = latitude
        self.longitude = longitude


def handle_rate_limit(e):
    if "Retry-After" in e.headers:
        wait_seconds = int(e.headers["Retry-After"]) + 5
        if wait_seconds < 1:
            wait_seconds = 1
        print(f'waiting {wait_seconds} seconds')
        time.sleep(wait_seconds)
    elif "x-ratelimit-reset" in e.headers:
        reset = int(e.headers["x-ratelimit-reset"])
        wait_time_seconds = reset - int(time.time()) + 5
        if wait_time_seconds < 1:
            wait_time_seconds = 1
        print(f'waiting {wait_time_seconds} seconds')
        time.sleep(wait_time_seconds)


if __name__ == '__main__':
    collect(os.getenv('GH_TOKEN'), os.getenv('TOM_TOM_TOKEN'), os.getenv('GH_USER'), os.getenv('ADDITIONAL_REPOS',None))
    create_map()
