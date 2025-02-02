# Standard Modules
from io import BytesIO
from PIL import Image
from urllib.parse import quote


# External Packages
from fastapi.testclient import TestClient

# Internal Packages
from khoj.main import app
from khoj.configure import configure_routes, configure_search_types
from khoj.utils import state
from khoj.utils.state import search_models, content_index, config
from khoj.search_type import text_search, image_search
from khoj.utils.rawconfig import ContentConfig, SearchConfig
from khoj.processor.org_mode.org_to_jsonl import OrgToJsonl
from khoj.search_filter.word_filter import WordFilter
from khoj.search_filter.file_filter import FileFilter


# Test
# ----------------------------------------------------------------------------------------------------
def test_search_with_invalid_content_type(client):
    # Arrange
    user_query = quote("How to call Khoj from Emacs?")

    # Act
    response = client.get(f"/api/search?q={user_query}&t=invalid_content_type")

    # Assert
    assert response.status_code == 422


# ----------------------------------------------------------------------------------------------------
def test_search_with_valid_content_type(client):
    for content_type in ["all", "org", "markdown", "image", "pdf", "github", "notion", "plugin1"]:
        # Act
        response = client.get(f"/api/search?q=random&t={content_type}")
        # Assert
        assert response.status_code == 200, f"Returned status: {response.status_code} for content type: {content_type}"


# ----------------------------------------------------------------------------------------------------
def test_update_with_invalid_content_type(client):
    # Act
    response = client.get(f"/api/update?t=invalid_content_type")

    # Assert
    assert response.status_code == 422


# ----------------------------------------------------------------------------------------------------
def test_regenerate_with_invalid_content_type(client):
    # Act
    response = client.get(f"/api/update?force=true&t=invalid_content_type")

    # Assert
    assert response.status_code == 422


# ----------------------------------------------------------------------------------------------------
def test_index_batch(client):
    # Arrange
    request_body = get_sample_files_data()
    headers = {"x-api-key": "secret"}

    # Act
    response = client.post("/indexer/batch", json=request_body, headers=headers)

    # Assert
    assert response.status_code == 200


# ----------------------------------------------------------------------------------------------------
def test_regenerate_with_valid_content_type(client):
    for content_type in ["all", "org", "markdown", "image", "pdf", "notion", "plugin1"]:
        # Arrange
        request_body = get_sample_files_data()

        headers = {"x-api-key": "secret"}

        # Act
        response = client.post(f"/indexer/batch?search_type={content_type}", json=request_body, headers=headers)
        # Assert
        assert response.status_code == 200, f"Returned status: {response.status_code} for content type: {content_type}"


# ----------------------------------------------------------------------------------------------------
def test_regenerate_with_github_fails_without_pat(client):
    # Act
    response = client.get(f"/api/update?force=true&t=github")

    # Arrange
    request_body = get_sample_files_data()

    headers = {"x-api-key": "secret"}

    # Act
    response = client.post(f"/indexer/batch?search_type=github", json=request_body, headers=headers)
    # Assert
    assert response.status_code == 200, f"Returned status: {response.status_code} for content type: github"


# ----------------------------------------------------------------------------------------------------
def test_get_configured_types_via_api(client):
    # Act
    response = client.get(f"/api/config/types")

    # Assert
    assert response.status_code == 200
    assert response.json() == ["all", "org", "image", "plaintext", "plugin1"]


# ----------------------------------------------------------------------------------------------------
def test_get_configured_types_with_only_plugin_content_config(content_config):
    # Arrange
    config.content_type = ContentConfig()
    config.content_type.plugins = content_config.plugins
    state.SearchType = configure_search_types(config)

    configure_routes(app)
    client = TestClient(app)

    # Act
    response = client.get(f"/api/config/types")

    # Assert
    assert response.status_code == 200
    assert response.json() == ["all", "plugin1"]


# ----------------------------------------------------------------------------------------------------
def test_get_configured_types_with_no_plugin_content_config(content_config):
    # Arrange
    config.content_type = content_config
    config.content_type.plugins = None
    state.SearchType = configure_search_types(config)

    configure_routes(app)
    client = TestClient(app)

    # Act
    response = client.get(f"/api/config/types")

    # Assert
    assert response.status_code == 200
    assert "plugin1" not in response.json()


# ----------------------------------------------------------------------------------------------------
def test_get_configured_types_with_no_content_config():
    # Arrange
    config.content_type = ContentConfig()
    state.SearchType = configure_search_types(config)

    configure_routes(app)
    client = TestClient(app)

    # Act
    response = client.get(f"/api/config/types")

    # Assert
    assert response.status_code == 200
    assert response.json() == ["all"]


# ----------------------------------------------------------------------------------------------------
def test_image_search(client, content_config: ContentConfig, search_config: SearchConfig):
    # Arrange
    search_models.image_search = image_search.initialize_model(search_config.image)
    content_index.image = image_search.setup(
        content_config.image, search_models.image_search.image_encoder, regenerate=False
    )
    query_expected_image_pairs = [
        ("kitten", "kitten_park.jpg"),
        ("a horse and dog on a leash", "horse_dog.jpg"),
        ("A guinea pig eating grass", "guineapig_grass.jpg"),
    ]

    for query, expected_image_name in query_expected_image_pairs:
        # Act
        response = client.get(f"/api/search?q={query}&n=1&t=image")

        # Assert
        assert response.status_code == 200
        actual_image = Image.open(BytesIO(client.get(response.json()[0]["entry"]).content))
        expected_image = Image.open(content_config.image.input_directories[0].joinpath(expected_image_name))

        # Assert
        assert expected_image == actual_image


# ----------------------------------------------------------------------------------------------------
def test_notes_search(client, content_config: ContentConfig, search_config: SearchConfig, sample_org_data):
    # Arrange
    search_models.text_search = text_search.initialize_model(search_config.asymmetric)
    content_index.org = text_search.setup(
        OrgToJsonl, sample_org_data, content_config.org, search_models.text_search.bi_encoder, regenerate=False
    )
    user_query = quote("How to git install application?")

    # Act
    response = client.get(f"/api/search?q={user_query}&n=1&t=org&r=true")

    # Assert
    assert response.status_code == 200
    # assert actual_data contains "Khoj via Emacs" entry
    search_result = response.json()[0]["entry"]
    assert "git clone https://github.com/khoj-ai/khoj" in search_result


# ----------------------------------------------------------------------------------------------------
def test_notes_search_with_only_filters(
    client, content_config: ContentConfig, search_config: SearchConfig, sample_org_data
):
    # Arrange
    filters = [WordFilter(), FileFilter()]
    search_models.text_search = text_search.initialize_model(search_config.asymmetric)
    content_index.org = text_search.setup(
        OrgToJsonl,
        sample_org_data,
        content_config.org,
        search_models.text_search.bi_encoder,
        regenerate=False,
        filters=filters,
    )
    user_query = quote('+"Emacs" file:"*.org"')

    # Act
    response = client.get(f"/api/search?q={user_query}&n=1&t=org")

    # Assert
    assert response.status_code == 200
    # assert actual_data contains word "Emacs"
    search_result = response.json()[0]["entry"]
    assert "Emacs" in search_result


# ----------------------------------------------------------------------------------------------------
def test_notes_search_with_include_filter(
    client, content_config: ContentConfig, search_config: SearchConfig, sample_org_data
):
    # Arrange
    filters = [WordFilter()]
    search_models.text_search = text_search.initialize_model(search_config.asymmetric)
    content_index.org = text_search.setup(
        OrgToJsonl, sample_org_data, content_config.org, search_models.text_search, regenerate=False, filters=filters
    )
    user_query = quote('How to git install application? +"Emacs"')

    # Act
    response = client.get(f"/api/search?q={user_query}&n=1&t=org")

    # Assert
    assert response.status_code == 200
    # assert actual_data contains word "Emacs"
    search_result = response.json()[0]["entry"]
    assert "Emacs" in search_result


# ----------------------------------------------------------------------------------------------------
def test_notes_search_with_exclude_filter(
    client, content_config: ContentConfig, search_config: SearchConfig, sample_org_data
):
    # Arrange
    filters = [WordFilter()]
    search_models.text_search = text_search.initialize_model(search_config.asymmetric)
    content_index.org = text_search.setup(
        OrgToJsonl,
        sample_org_data,
        content_config.org,
        search_models.text_search.bi_encoder,
        regenerate=False,
        filters=filters,
    )
    user_query = quote('How to git install application? -"clone"')

    # Act
    response = client.get(f"/api/search?q={user_query}&n=1&t=org")

    # Assert
    assert response.status_code == 200
    # assert actual_data does not contains word "clone"
    search_result = response.json()[0]["entry"]
    assert "clone" not in search_result


def get_sample_files_data():
    return {
        "org": {
            "path/to/filename.org": "* practicing piano",
            "path/to/filename1.org": "** top 3 reasons why I moved to SF",
            "path/to/filename2.org": "* how to build a search engine",
        },
        "pdf": {
            "path/to/filename.pdf": "Moore's law does not apply to consumer hardware",
            "path/to/filename1.pdf": "The sun is a ball of helium",
            "path/to/filename2.pdf": "Effect of sunshine on baseline human happiness",
        },
        "plaintext": {
            "path/to/filename.txt": "data,column,value",
            "path/to/filename1.txt": "<html>my first web page</html>",
            "path/to/filename2.txt": "2021-02-02 Journal Entry",
        },
        "markdown": {
            "path/to/filename.md": "# Notes from client call",
            "path/to/filename1.md": "## Studying anthropological records from the Fatimid caliphate",
            "path/to/filename2.md": "**Understanding science through the lens of art**",
        },
    }
