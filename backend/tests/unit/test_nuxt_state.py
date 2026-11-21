from typing import Any

import pytest

from salevault.scraper.sites.nuxt_state import (
    NuxtStateError,
    find_state_script,
    js_string,
    read_nuxt_state,
    read_state_script,
)


def page(script: str) -> str:
    return (
        '<html><head><script>window.dataLayer=[]</script></head><body><div id="__nuxt"></div>'
        f"<script>window.__NUXT__={script}</script>"
        '<script src="/assets/app.js" defer></script></body></html>'
    )


def test_reads_the_function_form_devalue_writes() -> None:
    script = (
        "(function(a,b,c,d,e){c.title=a;c.tags=d;d[0]=a;d[1]=b;e.self=c;"
        'return {layout:"default",data:[c],shared:[c,c],count:b,more:e}}'
        '("Text",72,{},Array(2),{}));'
    )

    state = read_nuxt_state(page(script))

    item = {"title": "Text", "tags": ["Text", 72]}
    assert state["layout"] == "default"
    assert state["data"] == [item]
    assert state["count"] == 72
    assert state["shared"][0] is state["data"][0]  # shared values stay shared
    assert state["more"] == {"self": item}


def test_reads_literals() -> None:
    script = (
        '{s:"a\\u002Fb \\"q\\" \\n",t:\'it\\\'s\',e:"",i:12,f:-1.5,x:1e3,z:-0,'
        'yes:true,no:false,nil:null,undef:void 0,holes:[1,,3,],nested:{"quoted key":[[]]},'
        '7:"number key",re:/^[0-9]{5}$/,inf:Infinity,date:new Date(1700000000000),'
        'set:new Set([1,2]),map:new Map([["k",1]]),boxed:Object("x"),bare:Object.create(null),'
        "assigned:Object.assign(Object.create(null),{a:1})}"
    )

    state = read_nuxt_state(page(script))

    assert state == {
        "s": 'a/b "q" \n',
        "t": "it's",
        "e": "",
        "i": 12,
        "f": -1.5,
        "x": 1000.0,
        "z": 0,
        "yes": True,
        "no": False,
        "nil": None,
        "undef": None,
        "holes": [1, None, 3],
        "nested": {"quoted key": [[]]},
        "7": "number key",
        "re": "/^[0-9]{5}$/",
        "inf": float("inf"),
        "date": 1700000000000,
        "set": [1, 2],
        "map": {"k": 1},
        "boxed": "x",
        "bare": {},
        "assigned": {"a": 1},
    }


def test_set_and_map_statements() -> None:
    script = (
        '(function(a,b){a.add(1).add("x");b.set("k",[1]).set(2,null);return [a,b]}'
        "(new Set,new Map))"
    )

    assert read_state_script(script) == [[1, "x"], {"k": [1], 2: None}]


@pytest.mark.parametrize(
    ("literal", "text"),
    [
        ('"plain"', "plain"),
        ('"\\u0428\\u043e\\u0440\\u0442\\u0438"', "\u0428\u043e\u0440\u0442\u0438"),
        ('"\\uD83D\\uDE00"', "\U0001f600"),  # a surrogate pair is one character
        ('"\\u{1F600}"', "\U0001f600"),
        ('"\\x41\\t\\\\"', "A\t\\"),
        ('"11\u00a0499 UAH"', "11\u00a0499 UAH"),
        ('"line\\\ncontinued"', "linecontinued"),
    ],
)
def test_string_escapes(literal: str, text: str) -> None:
    assert js_string(literal) == text


def test_more_parameters_than_arguments_are_undefined() -> None:
    assert read_state_script("(function(a,b){return {a:a,b:b}}(1))") == {"a": 1, "b": None}


def test_a_page_without_state() -> None:
    assert read_nuxt_state("<html><body><script>var x = 1</script></body></html>") is None
    assert find_state_script(page("{a:1}")) == "{a:1}"


@pytest.mark.parametrize(
    "script",
    [
        "{a:alert(1)}",  # a call
        "{a:1+1}",  # an operator
        "{a:b}",  # an unknown name
        "{a:window.location}",
        "{a:function(){}}",
        "(function(a){a=1;return a}(2))",  # assignment to a parameter itself
        "(function(a){a.x=fetch();return a}({}))",
        "(function(a){a[5]=1;return a}(Array(2)))",  # outside the array
        "(function(a){a.x=1;return a}(5))",  # not an object
        "(function(a){a.x=1}({}))",  # no return
        "(function(a){return a;a.x=1}({}))",  # statements after return
        "(function(a){return a}({})); alert(1)",  # code after the state
        "(function(a){return a}(b))",  # arguments cannot use names
        "{a:Array(10000000)}",
        "{a:new Function(1)}",
        "{a:Object.keys(1)}",
        "{a:[1 2]}",
        '{a:"unclosed}',
        "{a:1",
        "",
    ],
)
def test_anything_else_is_an_error(script: str) -> None:
    with pytest.raises(NuxtStateError):
        read_state_script(script)


def test_deep_nesting_is_an_error() -> None:
    with pytest.raises(NuxtStateError, match="deeply"):
        read_state_script("[" * 500 + "]" * 500)


def test_an_unclosed_script_is_an_error() -> None:
    with pytest.raises(NuxtStateError, match="not closed"):
        read_nuxt_state("<script>window.__NUXT__={a:1}")


def test_a_large_state_reads_quickly() -> None:
    names = [f"p{i}" for i in range(3000)]
    body = ";".join(f"o.k{i}=p{i}" for i in range(3000))
    args = ",".join(f'"value {i}"' for i in range(3000))
    script = f"(function(o,{','.join(names)}){{{body};return {{o:o}}}}({{}},{args}))"

    state: Any = read_state_script(script)

    assert state["o"]["k2999"] == "value 2999"
