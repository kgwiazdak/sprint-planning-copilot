import {Box, Stack, Typography} from '@mui/material';
import type {ReactNode} from 'react';

type PageHeaderProps = {
    eyebrow?: string;
    title: string;
    subtitle?: string;
    actions?: ReactNode;
};

export const PageHeader = ({
                               eyebrow,
                               title,
                               subtitle,
                               actions,
                           }: PageHeaderProps) => (
    <Stack
        direction={{xs: 'column', sm: 'row'}}
        alignItems={{xs: 'flex-start', sm: 'center'}}
        justifyContent="space-between"
        spacing={2}
        sx={{mb: 2, flexShrink: 0}}
    >
        <Stack spacing={0.5}>
            {eyebrow && (
                <Typography
                    variant="caption"
                    color="primary"
                    fontWeight={600}
                    letterSpacing={0.6}
                    textTransform="uppercase"
                >
                    {eyebrow}
                </Typography>
            )}
            <Typography
                variant="h4"
                fontWeight={700}
                sx={{fontSize: {xs: 26, md: 32}}}
            >
                {title}
            </Typography>
            {subtitle && (
                <Typography variant="body1" color="text.secondary">
                    {subtitle}
                </Typography>
            )}
        </Stack>
        {actions && (
            <Box display="flex" gap={1} flexWrap="wrap">
                {actions}
            </Box>
        )}
    </Stack>
);
