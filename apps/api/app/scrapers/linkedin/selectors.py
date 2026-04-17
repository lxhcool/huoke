from __future__ import annotations


class LinkedinSelectors:
    login_username_input_candidates = [
        "input#username",
        "input[name='session_key']",
        "input[name='username']",
    ]

    login_password_input_candidates = [
        "input#password",
        "input[name='session_password']",
        "input[name='password']",
        "input[type='password']",
    ]

    login_submit_candidates = [
        "button[type='submit']",
        "button:has-text('Sign in')",
        "button:has-text('登录')",
    ]

    login_success_candidates = [
        "input[placeholder*='Search']",
        "input[aria-label*='Search']",
        "a[href='/feed/']",
        "a[href*='/mynetwork/']",
    ]

    company_result_row_candidates = [
        "ul.reusable-search__entity-result-list > li",
        "main ul > li",
        ".search-results-container li",
    ]

    contact_result_row_candidates = [
        "ul.reusable-search__entity-result-list > li",
        "main ul > li",
        ".search-results-container li",
    ]

