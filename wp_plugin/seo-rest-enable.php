<?php
/**
 * Plugin Name: AI Content Hub - Yoast SEO REST Enabler
 * Description: Opens Yoast SEO fields (_yoast_wpseo_title, etc.) for REST API (Application Passwords) editing.
 * Version: 1.0
 * Author: AI Content Hub
 */

add_action('rest_api_init', function () {
    $meta_keys = [
        '_yoast_wpseo_title',
        '_yoast_wpseo_metadesc',
        '_yoast_wpseo_focuskw',
        '_yoast_wpseo_canonical',
    ];

    foreach ($meta_keys as $meta_key) {
        register_meta('post', $meta_key, [
            'show_in_rest' => true,
            'single'       => true,
            'type'         => 'string',
            'auth_callback' => function() {
                return current_user_can('edit_posts');
            }
        ]);
    }
});
