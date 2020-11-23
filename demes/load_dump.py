"""
Functions to load and dump graphs in YAML and JSON formats.
"""
import json

import strictyaml

import demes
from .schema import deme_graph_schema


def loads_asdict(string, *, format="yaml"):
    """
    Load a YAML or JSON string into a dictionary of nested objects.
    The keywords and structure of the string are defined by the
    :ref:`schema <sec_schema>`.

    :param str string: The string to be loaded.
    :param str format: The format of the input string. Either "yaml" or "json".
    :return: A dictionary of nested objects, with the same data model as the
        YAML or JSON input string.
    :rtype: dict
    """
    if format == "json":
        data = json.loads(string)
    elif format == "yaml":
        yaml = strictyaml.dirty_load(
            string, schema=deme_graph_schema, allow_flow_style=True
        )
        data = yaml.data
    else:
        raise ValueError(f"unknown format: {format}")
    return data


def load_asdict(filename, *, format="yaml"):
    """
    Load a YAML or JSON file into a dictionary of nested objects.
    The keywords and structure of the string are defined by the
    :ref:`schema <sec_schema>`.

    :param filename: The path to the file to be loaded.
    :type filename: str or :class:`os.PathLike`
    :param str format: The format of the input string. Either "yaml" or "json".
    :return: A dictionary of nested objects, with the same data model as the
        YAML or JSON input string.
    :rtype: dict
    """
    with open(filename) as f:
        return loads_asdict(f.read(), format=format)


def loads(string, *, format="yaml"):
    """
    Load a graph from a YAML or JSON string.
    The keywords and structure of the string are defined by the
    :ref:`schema <sec_schema>`.

    :param str string: The string to be loaded.
    :param str format: The format of the input string. Either "yaml" or "json".
    :return: A graph.
    :rtype: .Graph
    """
    data = loads_asdict(string, format=format)
    return demes.Graph.fromdict(data)


def load(filename, *, format="yaml"):
    """
    Load a graph from a YAML or JSON file.
    The keywords and structure of the file are defined by the
    :ref:`schema <sec_schema>`.

    :param filename: The path to the file to be loaded.
    :type filename: str or :class:`os.PathLike`
    :param str format: The format of the input file. Either "yaml" or "json".
    :return: A graph.
    :rtype: .Graph
    """
    data = load_asdict(filename, format=format)
    return demes.Graph.fromdict(data)


def dumps(graph, *, format="yaml"):
    """
    Dump the specified graph to a YAML or JSON string.
    The keywords and structure of the string are defined by the
    :ref:`schema <sec_schema>`.

    :param .Graph graph: The graph to dump.
    :param str format: The format of the output file. Either "yaml" or "json".
    :return: The YAML or JSON string.
    :rtype: str
    """
    data = graph.asdict()

    if format == "json":
        string = json.dumps(data)
    elif format == "yaml":
        doc = strictyaml.as_document(data, schema=deme_graph_schema)
        string = doc.as_yaml()
    else:
        raise ValueError(f"unknown format: {format}")

    return string


def dump(graph, filename, *, format="yaml"):
    """
    Dump the specified graph to a file.
    The keywords and structure of the file are defined by the
    :ref:`schema <sec_schema>`.

    :param .Graph graph: The graph to dump.
    :param filename: Path to the output file.
    :type filename: str or :class:`os.PathLike`
    :param str format: The format of the output file. Either "yaml" or "json".
    """
    with open(filename, "w") as f:
        f.write(dumps(graph, format=format))